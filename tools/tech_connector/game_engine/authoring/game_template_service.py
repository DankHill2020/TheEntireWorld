"""Versioned, playable project templates assembled from first-class TC assets.

The template layer deliberately contains recipes, not a second gameplay runtime.
Every generated project is editable through the same Level, Prefab, Input Map,
Physics Scene, Ruleset, and Build Profile assets used by the rest of the editor.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from tech_connector.game_engine.assets.asset_database_service import AssetDatabase
from tech_connector.game_engine.assets.asset_operations_service import AssetOperationsService
from tech_connector.game_engine.assets.asset_type_registry import AssetTypeRegistry, builtin_asset_type_registry
from tech_connector.game_engine.assets.build_profile_service import plan_build_profile
from tech_connector.game_engine.assets.character_asset_service import (
    validate_character_lods,
    validate_skin_binding_properties,
)
from tech_connector.game_engine.assets.input_map_service import audit_input_map
from tech_connector.game_engine.assets.locomotion_service import locomotion_preset, validate_locomotion_controller
from tech_connector.game_engine.assets.physics_asset_service import validate_physics_asset_properties
from tech_connector.game_engine.assets.prefab_service import PrefabService
from tech_connector.game_engine.assets.rig_asset_service import validate_control_rig_properties, validate_ik_rig_properties
from tech_connector.game_engine.assets.starter_character_service import (
    STARTER_SKIN_RUNTIME_ID, StarterCharacterReceipt, StarterCharacterService,
)
from tech_connector.game_engine.authoring.game_experience_service import (
    attach_game_experience,
    create_game_experience_profile,
)
from tech_connector.game_engine.authoring.presentation_profile_service import (
    compile_presentation_plan,
    create_presentation_profile,
    validate_presentation_profile,
)
from tech_connector.game_engine.runtime.tc_player_build_service import compile_tcscene_for_runtime
from tech_connector.game_engine.scene.federated_scene_service import load_federated_scene, save_federated_scene


GAME_TEMPLATE_SCHEMA = "tech_connector.game_template_catalog.v1"
GAME_TEMPLATE_RECEIPT_SCHEMA = "tech_connector.game_template_instantiation.v1"
PLAY_READINESS_SCHEMA = "tech_connector.play_readiness.v1"


@dataclass(frozen=True)
class GameTemplateVariant:
    template_id: str
    variant_id: str
    display_name: str
    description: str
    dimensionality: str
    game_types: tuple[str, ...]
    camera_mode: str
    movement_mode: str
    default_visual_style: str = "stylized_pbr"
    maturity: str = "production"

    @property
    def qualified_id(self) -> str:
        return f"{self.template_id}/{self.variant_id}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"qualified_id": self.qualified_id}


@dataclass(frozen=True)
class GameTemplateReceipt:
    template_id: str
    variant_id: str
    visual_style: str
    level_asset_id: str
    player_prefab_asset_id: str
    input_map_asset_id: str
    locomotion_controller_asset_id: str
    skeleton_asset_id: str
    skeletal_mesh_asset_id: str
    skin_binding_asset_id: str
    character_material_asset_id: str
    character_texture_asset_id: str
    ik_rig_asset_id: str
    control_rig_asset_id: str
    character_physics_asset_id: str
    physics_scene_asset_id: str
    ruleset_asset_id: str
    build_profile_asset_id: str
    created_asset_ids: tuple[str, ...]
    validation: dict[str, Any]

    @property
    def ready_to_play(self) -> bool:
        return bool(self.validation.get("ready_to_play"))

    def to_dict(self) -> dict[str, Any]:
        return {"schema": GAME_TEMPLATE_RECEIPT_SCHEMA, **asdict(self), "ready_to_play": self.ready_to_play}


_TEMPLATES: tuple[GameTemplateVariant, ...] = (
    GameTemplateVariant(
        "playable_sandbox", "standard", "Playable Sandbox", "A safe, lit physics playground that starts in Play immediately.",
        "3d", ("sandbox", "action"), "third_person", "free_3d",
    ),
    GameTemplateVariant(
        "third_person", "exploration", "Third Person — Exploration", "Over-the-shoulder traversal with a reusable player prefab.",
        "3d", ("action",), "third_person", "free_3d", maturity="preview",
    ),
    GameTemplateVariant(
        "third_person", "combat", "Third Person — Combat", "Third-person movement with combat-ready input actions and targeting.",
        "3d", ("action",), "third_person", "free_3d", maturity="preview",
    ),
    GameTemplateVariant(
        "first_person", "shooter", "First Person — Shooter", "First-person movement, look, jump, fire, aim, and reload actions.",
        "3d", ("action",), "first_person", "free_3d", maturity="preview",
    ),
    GameTemplateVariant(
        "side_scroller", "platformer", "Side Scroller — Platformer", "A constrained movement plane with a side-on camera and platforming assists.",
        "2.5d", ("platformer", "action"), "side", "plane_2d", maturity="preview",
    ),
    GameTemplateVariant(
        "fighting", "versus", "Fighting — Versus", "A two-player fighting foundation with attacks, guard, throw, and round actions.",
        "2.5d", ("action",), "fighting", "plane_2d", maturity="preview",
    ),
)


def available_game_templates() -> tuple[dict[str, Any], ...]:
    """Return the user-facing catalog with explicit maturity per variant."""

    return tuple(item.to_dict() for item in _TEMPLATES)


def resolve_game_template(template_id: str, variant_id: str = "") -> GameTemplateVariant:
    template_key = str(template_id).strip().casefold().replace(" ", "_")
    variant_key = str(variant_id).strip().casefold().replace(" ", "_")
    candidates = [item for item in _TEMPLATES if item.template_id == template_key]
    if not candidates:
        raise KeyError(f"Unknown game template: {template_id}")
    if not variant_key:
        return candidates[0]
    for item in candidates:
        if item.variant_id == variant_key:
            return item
    raise KeyError(f"Unknown variant '{variant_id}' for template '{template_id}'.")


class GameTemplateService:
    """Create an editable, dependency-closed playable project slice."""

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
        self.prefabs = PrefabService(self.project_root, database)

    def create_project(
        self,
        *,
        template_id: str = "playable_sandbox",
        variant_id: str = "",
        visual_style: str = "",
        project_name: str = "StarterGame",
        platform: str = "windows",
        root_folder: str | Path = "Assets",
    ) -> GameTemplateReceipt:
        recipe = resolve_game_template(template_id, variant_id)
        style = str(visual_style or recipe.default_visual_style)
        safe_prefix = _safe_prefix(project_name)
        root = Path(root_folder)
        created: list[str] = []
        character_source_path = ""
        try:
            inputs = self.operations.create_asset(
                "tc.input_map", f"IM_{safe_prefix}", folder=root / "Input", properties=_input_properties(recipe),
            )
            created.append(inputs.asset_id)
            locomotion_properties = locomotion_preset(
                _locomotion_preset_id(recipe), movement_mode=recipe.movement_mode,
            )
            locomotion_properties["animation_slots"].update({
                "idle": "tc_idle", "walk_forward": "tc_walk",
                "walk_forward_left": "tc_walk_forward_left", "walk_forward_right": "tc_walk_forward_right",
                "walk_backward": "tc_walk_backward", "walk_backward_left": "tc_walk_backward_left",
                "walk_backward_right": "tc_walk_backward_right",
                "strafe_left": "tc_walk_left", "strafe_right": "tc_walk_right", "run_forward": "tc_run",
                "jump_start": "tc_jump", "jump_loop": "tc_jump", "land": "tc_land",
                "start_forward": "tc_start_forward", "stop_forward": "tc_stop_forward",
                "pivot_left": "tc_pivot_left", "pivot_right": "tc_pivot_right",
                "crouch_idle": "tc_crouch_idle", "crouch_walk": "tc_crouch_walk", "fall": "tc_fall",
            })
            locomotion = self.operations.create_asset(
                "tc.animation_controller", f"AC_{safe_prefix}_Locomotion",
                folder=root / "Animation" / "Locomotion",
                properties=locomotion_properties,
            )
            created.append(locomotion.asset_id)
            starter_characters = StarterCharacterService(self.project_root, self.database, self.registry)
            character = starter_characters.create(
                f"{safe_prefix}_Mannequin", visual_style=style,
                dimensionality=recipe.dimensionality, folder=root / "Characters" / "Starter",
            )
            character_source_path = character.mesh_source_path
            created.extend((
                character.skeleton_asset_id, character.texture_asset_id, character.material_asset_id,
                character.ik_rig_asset_id, character.control_rig_asset_id,
                character.skin_binding_asset_id, character.skeletal_mesh_asset_id, character.physics_asset_id,
            ))
            physics = self.operations.create_asset(
                "tc.physics_scene", f"PS_{safe_prefix}", folder=root / "Physics", properties=_physics_properties(),
            )
            created.append(physics.asset_id)
            player = self.prefabs.create_from_entities(
                f"PF_{safe_prefix}_Player", [_player_entity(recipe, locomotion.asset_id, character)],
                folder=root / "Gameplay" / "Players",
                exposed_properties={
                    "move_speed": 5.5, "jump_impulse": 6.5, "camera_mode": recipe.camera_mode,
                    "movement_mode": recipe.movement_mode, "input_map_asset_id": inputs.asset_id,
                    "locomotion_controller_asset_id": locomotion.asset_id,
                    "skeleton_asset_id": character.skeleton_asset_id,
                    "skeletal_mesh_asset_id": character.skeletal_mesh_asset_id,
                    "skin_binding_asset_id": character.skin_binding_asset_id,
                    "material_asset_id": character.material_asset_id,
                    "texture_asset_id": character.texture_asset_id,
                    "ik_rig_asset_id": character.ik_rig_asset_id,
                    "control_rig_asset_id": character.control_rig_asset_id,
                    "physics_asset_id": character.physics_asset_id,
                },
                dependencies=[
                    inputs.asset_id, locomotion.asset_id, character.skeleton_asset_id,
                    character.skeletal_mesh_asset_id, character.skin_binding_asset_id,
                    character.material_asset_id, character.texture_asset_id,
                    character.ik_rig_asset_id, character.control_rig_asset_id, character.physics_asset_id,
                ],
            )
            created.append(player.asset_id)
            level = self.operations.create_asset("tc.level", f"L_{safe_prefix}_Default", folder=root / "Levels")
            created.append(level.asset_id)
            self._author_level(
                level.asset_id, recipe, style, player.asset_id, inputs.asset_id,
                locomotion.asset_id, physics.asset_id, character,
            )
            rules = self.operations.create_asset(
                "tc.game_ruleset", f"GR_{safe_prefix}", folder=root / "Gameplay", properties={
                    "default_level": level.asset_id,
                    "default_player": player.asset_id,
                    "input_map": inputs.asset_id,
                    "physics_scene": physics.asset_id,
                    "default_locomotion": locomotion.asset_id,
                    "default_skeleton": character.skeleton_asset_id,
                    "default_skeletal_mesh": character.skeletal_mesh_asset_id,
                    "default_skin_binding": character.skin_binding_asset_id,
                    "default_character_material": character.material_asset_id,
                    "default_character_texture": character.texture_asset_id,
                    "default_ik_rig": character.ik_rig_asset_id,
                    "default_control_rig": character.control_rig_asset_id,
                    "default_character_physics": character.physics_asset_id,
                },
            )
            created.append(rules.asset_id)
            self.database.set_dependencies(rules.asset_id, [
                (level.asset_id, "default_level"), (player.asset_id, "default_player"),
                (inputs.asset_id, "input_map"), (physics.asset_id, "physics_scene"),
                (locomotion.asset_id, "default_locomotion"),
                (character.skeleton_asset_id, "default_skeleton"),
                (character.skeletal_mesh_asset_id, "default_skeletal_mesh"),
                (character.skin_binding_asset_id, "default_skin_binding"),
                (character.material_asset_id, "default_character_material"),
                (character.texture_asset_id, "default_character_texture"),
                (character.ik_rig_asset_id, "default_ik_rig"),
                (character.control_rig_asset_id, "default_control_rig"),
                (character.physics_asset_id, "default_character_physics"),
            ])
            build = self.operations.create_asset(
                "tc.build_profile", f"BP_{safe_prefix}_Development", folder=root / "Build", properties={
                    "platform": str(platform).casefold(), "configuration": "development",
                    "entry_level": level.asset_id, "quality_profile": _quality_for_style(style),
                    "included_levels": [level.asset_id], "incremental": True,
                    "output_directory": "Build", "include_debug_symbols": True,
                },
            )
            created.append(build.asset_id)
            self.database.set_dependencies(build.asset_id, [
                (level.asset_id, "entry_level"), (rules.asset_id, "ruleset"),
            ])
            validation = self.validate_project(rules.asset_id, build.asset_id)
            return GameTemplateReceipt(
                recipe.template_id, recipe.variant_id, style, level.asset_id, player.asset_id,
                inputs.asset_id, locomotion.asset_id, character.skeleton_asset_id,
                character.skeletal_mesh_asset_id, character.skin_binding_asset_id,
                character.material_asset_id, character.texture_asset_id,
                character.ik_rig_asset_id, character.control_rig_asset_id, character.physics_asset_id,
                physics.asset_id, rules.asset_id,
                build.asset_id, tuple(created), validation,
            )
        except Exception:
            self._rollback(created)
            if character_source_path:
                Path(character_source_path).unlink(missing_ok=True)
            raise

    def validate_project(self, ruleset_asset_id: str, build_profile_asset_id: str = "") -> dict[str, Any]:
        issues: list[dict[str, str]] = []
        rules = self._properties(ruleset_asset_id, "tc.game_ruleset")
        expected = {
            "default_level": "tc.level", "default_player": "tc.prefab",
            "input_map": "tc.input_map", "physics_scene": "tc.physics_scene",
            "default_locomotion": "tc.animation_controller",
            "default_skeleton": "tc.skeleton",
            "default_skeletal_mesh": "tc.skeletal_mesh",
            "default_skin_binding": "tc.skin_binding",
            "default_character_material": "tc.material",
            "default_character_texture": "tc.texture",
            "default_ik_rig": "tc.ik_rig",
            "default_control_rig": "tc.control_rig",
            "default_character_physics": "tc.physics_asset",
        }
        records: dict[str, Any] = {}
        for field, asset_type in expected.items():
            asset_id = str(rules.get(field) or "")
            record = self.database.asset(asset_id) if asset_id else None
            records[field] = record
            if record is None:
                issues.append(_issue("error", f"missing_{field}", f"Ruleset has no available {field.replace('_', ' ')} asset."))
            elif record.asset_type != asset_type:
                issues.append(_issue("error", f"invalid_{field}_type", f"{field.replace('_', ' ').title()} must be {asset_type}."))

        input_record = records.get("input_map")
        if input_record is not None and input_record.asset_type == "tc.input_map":
            audit = audit_input_map(self._properties(input_record.asset_id, "tc.input_map"))
            issues.extend(item.to_dict() for item in audit.diagnostics if item.severity == "error")

        locomotion_record = records.get("default_locomotion")
        if locomotion_record is not None and locomotion_record.asset_type == "tc.animation_controller":
            issues.extend(
                item.to_dict() for item in validate_locomotion_controller(
                    self._properties(locomotion_record.asset_id, "tc.animation_controller")
                )
            )
        mesh_record = records.get("default_skeletal_mesh")
        if mesh_record is not None and mesh_record.asset_type == "tc.skeletal_mesh":
            issues.extend(
                asdict(item) for item in validate_character_lods(
                    self._properties(mesh_record.asset_id, "tc.skeletal_mesh")
                )
            )
        skin_record = records.get("default_skin_binding")
        if skin_record is not None and skin_record.asset_type == "tc.skin_binding":
            issues.extend(
                asdict(item) for item in validate_skin_binding_properties(
                    self._properties(skin_record.asset_id, "tc.skin_binding")
                )
            )
        ik_record = records.get("default_ik_rig")
        if ik_record is not None and ik_record.asset_type == "tc.ik_rig":
            issues.extend(
                asdict(item) for item in validate_ik_rig_properties(
                    self._properties(ik_record.asset_id, "tc.ik_rig")
                )
            )
        control_rig_record = records.get("default_control_rig")
        if control_rig_record is not None and control_rig_record.asset_type == "tc.control_rig":
            issues.extend(
                asdict(item) for item in validate_control_rig_properties(
                    self._properties(control_rig_record.asset_id, "tc.control_rig")
                )
            )
        character_physics_record = records.get("default_character_physics")
        if character_physics_record is not None and character_physics_record.asset_type == "tc.physics_asset":
            issues.extend(
                asdict(item) for item in validate_physics_asset_properties(
                    self._properties(character_physics_record.asset_id, "tc.physics_asset")
                )
            )
        player_record = records.get("default_player")
        if player_record is not None and player_record.asset_type == "tc.prefab" and locomotion_record is not None:
            player_properties = self._properties(player_record.asset_id, "tc.prefab")
            exposed = dict(player_properties.get("exposed_properties") or {})
            if str(exposed.get("locomotion_controller_asset_id") or "") != locomotion_record.asset_id:
                issues.append(_issue(
                    "error", "player_locomotion_not_bound",
                    "The default player prefab is not bound to the Ruleset's Locomotion Controller.",
                ))
            for field, exposed_field, label in (
                ("default_skeleton", "skeleton_asset_id", "Skeleton"),
                ("default_skeletal_mesh", "skeletal_mesh_asset_id", "Skeletal Mesh"),
                ("default_skin_binding", "skin_binding_asset_id", "Skin Binding"),
                ("default_character_material", "material_asset_id", "Character Material"),
                ("default_character_texture", "texture_asset_id", "Character Texture"),
                ("default_ik_rig", "ik_rig_asset_id", "IK Rig"),
                ("default_control_rig", "control_rig_asset_id", "Control Rig"),
                ("default_character_physics", "physics_asset_id", "Character Physics Asset"),
            ):
                expected_record = records.get(field)
                if expected_record is not None and str(exposed.get(exposed_field) or "") != expected_record.asset_id:
                    issues.append(_issue(
                        "error", f"player_{field}_not_bound",
                        f"The default player prefab is not bound to the Ruleset's {label}.",
                    ))

        level_record = records.get("default_level")
        runtime_receipt: dict[str, Any] = {}
        if level_record is not None and level_record.asset_type == "tc.level":
            document, _blobs = load_federated_scene(level_record.source_path)
            runtime = dict(document.metadata.get("runtime_world") or {})
            entities = [dict(item) for item in runtime.get("entities") or () if isinstance(item, Mapping)]
            if not any(dict(item.get("camera") or {}).get("active") for item in entities):
                issues.append(_issue("error", "missing_active_camera", "The entry Level needs an active camera."))
            if not any(item.get("light") for item in entities) and not dict(runtime.get("rendering") or {}).get("environment_texture"):
                issues.append(_issue("error", "missing_lighting", "The entry Level needs a light or environment."))
            player_entities = [item for item in entities if item.get("role") == "player" or item.get("name") == "Player"]
            if not player_entities:
                issues.append(_issue("error", "missing_player_spawn", "The entry Level needs a player spawn."))
            elif not dict(player_entities[0].get("collider") or {}):
                issues.append(_issue("error", "player_has_no_collider", "The default player needs collision."))
            elif str(dict(player_entities[0].get("render") or {}).get("skin_binding") or "") != STARTER_SKIN_RUNTIME_ID:
                issues.append(_issue(
                    "error", "player_has_no_runtime_skin",
                    "The default player's starter mesh is not connected to its runtime Skin Binding.",
                ))
            if not any(item.get("role") == "walkable_surface" and item.get("collider") for item in entities):
                issues.append(_issue("error", "missing_walkable_surface", "The entry Level needs a collidable walkable surface."))
            if not runtime.get("tick"):
                issues.append(_issue("error", "missing_player_control", "The entry Level needs a runtime player-control graph."))
            runtime_operations = {
                str(row.get("operation") or "") for row in runtime.get("tick") or () if isinstance(row, Mapping)
            }
            required_locomotion = {"character.move", "character.jump", "camera.follow"}
            required_locomotion.add("animation.locomotion")
            missing_locomotion = sorted(required_locomotion - runtime_operations)
            if missing_locomotion:
                issues.append(_issue(
                    "error", "incomplete_locomotion_runtime",
                    "The entry Level is missing locomotion operations: " + ", ".join(missing_locomotion),
                ))
            try:
                compiled = compile_tcscene_for_runtime(
                    level_record.source_path,
                    self.project_root / ".tech_connector" / "template_validation" / f"{level_record.asset_id}.tcruntime",
                )
                runtime_receipt = compiled.to_dict()
                issues.extend(_issue("warning", "runtime_compile_warning", message) for message in compiled.warnings)
            except Exception as exc:
                issues.append(_issue("error", "runtime_compile_failed", f"The entry Level could not compile: {exc}"))

        build_plan: dict[str, Any] = {}
        if build_profile_asset_id:
            try:
                planned_build = plan_build_profile(
                    self.database, self._properties(build_profile_asset_id, "tc.build_profile")
                )
                build_plan = planned_build.to_dict()
                issues.extend(asdict(item) for item in planned_build.diagnostics)
            except (KeyError, ValueError) as exc:
                issues.append(_issue("error", "invalid_build_profile", str(exc)))

        ready = not any(item.get("severity") == "error" for item in issues)
        return {
            "schema": PLAY_READINESS_SCHEMA,
            "ready_to_play": ready,
            "ruleset_asset_id": str(ruleset_asset_id),
            "build_profile_asset_id": str(build_profile_asset_id),
            "entry_level_asset_id": str(rules.get("default_level") or ""),
            "issues": issues,
            "runtime_compile": runtime_receipt,
            "build_plan": build_plan,
            "checks": {
                "asset_references": all(records.values()),
                "input_conflicts": not any(item.get("code") == "binding_conflict" for item in issues),
                "runtime_compiles": bool(runtime_receipt),
                "package_dependency_closure": bool(build_plan.get("asset_ids")),
            },
        }

    def _author_level(
        self,
        level_asset_id: str,
        recipe: GameTemplateVariant,
        visual_style: str,
        player_prefab_id: str,
        input_map_id: str,
        locomotion_controller_id: str,
        physics_scene_id: str,
        character: StarterCharacterReceipt,
    ) -> None:
        record = self.database.asset(level_asset_id)
        if record is None:
            raise KeyError(level_asset_id)
        document, blobs = load_federated_scene(record.source_path)
        presentation = create_presentation_profile(
            f"{recipe.template_id}_{recipe.variant_id}_presentation", visual_style,
            dimensionality=recipe.dimensionality,
        )
        presentation_plan = compile_presentation_plan(presentation)
        presentation_validation = validate_presentation_profile(presentation)
        experience = create_game_experience_profile(
            f"{recipe.template_id}_{recipe.variant_id}_experience", recipe.game_types,
        )
        experience.presentation = presentation
        attach_game_experience(document, experience)
        document.metadata["presentation_profile"] = presentation.to_dict()
        document.metadata["presentation_compile_plan"] = presentation_plan
        document.metadata["presentation_validation"] = presentation_validation
        document.metadata["template_source"] = {
            "schema": GAME_TEMPLATE_SCHEMA, "template_id": recipe.template_id,
            "variant_id": recipe.variant_id, "catalog_version": 1,
        }
        character_blobs = StarterCharacterService(self.project_root, self.database, self.registry).attach_to_level(
            document, character,
        )
        blobs.update(character_blobs)
        document.metadata["starter_character"] = character.to_dict()
        document.metadata["runtime_world"] = _runtime_world(
            recipe, visual_style, locomotion_controller_id, character,
        )
        save_federated_scene(record.source_path, document, blobs=blobs)
        self.database.register_asset(
            record.source_path, record.asset_type, asset_id=record.asset_id, metadata=record.metadata,
            dependencies=[
                (player_prefab_id, "default_player"), (input_map_id, "input_map"),
                (locomotion_controller_id, "locomotion_controller"),
                (character.skeleton_asset_id, "skeleton"),
                (character.skeletal_mesh_asset_id, "skeletal_mesh"),
                (character.skin_binding_asset_id, "skin_binding"),
                (character.material_asset_id, "character_material"),
                (character.texture_asset_id, "character_texture"),
                (character.ik_rig_asset_id, "ik_rig"),
                (character.control_rig_asset_id, "control_rig"),
                (character.physics_asset_id, "character_physics"),
                (physics_scene_id, "physics_scene"),
            ],
        )

    def _properties(self, asset_id: str, expected_type: str) -> dict[str, Any]:
        import json

        record = self.database.asset(str(asset_id))
        if record is None or record.asset_type != expected_type:
            raise KeyError(f"Expected {expected_type} asset: {asset_id}")
        payload = json.loads(record.source_path.read_text(encoding="utf-8"))
        return dict(payload.get("properties") or {})

    def _rollback(self, created_asset_ids: list[str]) -> None:
        for asset_id in reversed(created_asset_ids):
            if self.database.asset(asset_id) is None:
                continue
            try:
                self.operations.delete_asset(asset_id, _record_undo=False)
            except Exception:
                # Preserve the original generation exception. Reverse dependency
                # order normally makes every generated asset removable.
                pass


def _input_properties(recipe: GameTemplateVariant) -> dict[str, Any]:
    context = [{"id": "Gameplay", "priority": 0, "enabled": True}]

    def binding(key: str, *, device: str = "keyboard_mouse", scale: float = 1.0) -> dict[str, Any]:
        return {"context": "Gameplay", "device": device, "key": key, "scale": scale, "consume": True}

    actions: dict[str, dict[str, Any]] = {
        "Move": {"value_type": "axis2d", "bindings": [
            binding("W"), binding("S", scale=-1.0), binding("A", scale=-1.0), binding("D"),
            binding("LeftStick", device="gamepad"),
        ]},
        "Look": {"value_type": "axis2d", "bindings": [
            binding("MouseDelta"), binding("RightStick", device="gamepad"),
        ]},
        "Jump": {"value_type": "button", "bindings": [binding("Space"), binding("GamepadSouth", device="gamepad")]},
        "Pause": {"value_type": "button", "bindings": [binding("Escape"), binding("GamepadStart", device="gamepad")]},
    }
    if recipe.template_id in {"first_person", "third_person", "fighting"}:
        actions.update({
            "PrimaryAction": {"value_type": "button", "bindings": [binding("MouseLeft"), binding("RightTrigger", device="gamepad")]},
            "SecondaryAction": {"value_type": "button", "bindings": [binding("MouseRight"), binding("LeftTrigger", device="gamepad")]},
        })
    if recipe.template_id == "first_person":
        actions["Reload"] = {"value_type": "button", "bindings": [binding("R"), binding("GamepadWest", device="gamepad")]}
    if recipe.template_id == "fighting":
        actions.update({
            "Guard": {"value_type": "button", "bindings": [binding("LeftShift"), binding("LeftBumper", device="gamepad")]},
            "Throw": {"value_type": "button", "bindings": [binding("E"), binding("RightBumper", device="gamepad")]},
        })
    return {"contexts": context, "actions": actions}


def _physics_properties() -> dict[str, Any]:
    return {
        "gravity": [0.0, -9.80665, 0.0], "fixed_time_step": 1.0 / 120.0,
        "solver_iterations": 12,
        "collision_layers": {
            "WorldStatic": {"collides_with": ["Player", "WorldDynamic"]},
            "WorldDynamic": {"collides_with": ["WorldStatic", "Player", "WorldDynamic"]},
            "Player": {"collides_with": ["WorldStatic", "WorldDynamic"]},
            "Trigger": {"overlaps_with": ["Player"]},
        },
    }


def _player_entity(
    recipe: GameTemplateVariant,
    locomotion_controller_id: str = "",
    character: StarterCharacterReceipt | None = None,
) -> dict[str, Any]:
    mesh_source = character.mesh_source_path if character is not None else "builtin:capsule"
    return {
        "name": "Player", "role": "player",
        "transform": {"position": [0.0, 1.25, 0.0]},
        "render": {
            "mesh": mesh_source, "skin_binding": STARTER_SKIN_RUNTIME_ID if character is not None else "",
            "material_asset_id": character.material_asset_id if character is not None else "",
            "base_color_texture": character.texture_source_path if character is not None else "",
            "base_color": [0.12, 0.48, 0.82], "roughness": 0.42, "metallic": 0.05,
            "presentation_variant": character.presentation_variant if character is not None else "proxy",
        },
        "rigid_body": {"mass": 80.0, "dynamic": True, "continuous_collision": True, "linear_damping": 0.08},
        "collider": {"shape": "capsule", "radius": 0.45, "half_height": 0.9, "half_extents": [0.45, 0.9, 0.45], "layer": 4},
        "character_controller": {
            "locomotion_controller_asset_id": str(locomotion_controller_id),
            "movement_mode": recipe.movement_mode, "camera_mode": recipe.camera_mode,
            "move_speed": 5.5, "acceleration": 30.0, "deceleration": 38.0,
            "jump_impulse": 6.5, "air_control": 0.35, "step_height": 0.35,
            "slope_limit_degrees": 48.0, "coyote_time_seconds": 0.1,
            "jump_buffer_seconds": 0.12,
            "ik_rig_asset_id": character.ik_rig_asset_id if character is not None else "",
            "control_rig_asset_id": character.control_rig_asset_id if character is not None else "",
            "physics_asset_id": character.physics_asset_id if character is not None else "",
        },
    }


def _runtime_world(
    recipe: GameTemplateVariant, visual_style: str, locomotion_controller_id: str,
    character: StarterCharacterReceipt,
) -> dict[str, Any]:
    camera_position = {
        "first_person": [0.0, 1.65, 0.05], "side": [0.0, 3.0, -14.0],
        "fighting": [0.0, 3.2, -13.0], "third_person": [0.0, 4.2, -9.5],
    }[recipe.camera_mode]
    pixel = visual_style.casefold().startswith("pixel_")
    toon = visual_style.casefold() in {"toon", "vector_flat", "hand_painted", "low_poly", "retro_3d"}
    world = {
        "hud_text": f"{recipe.display_name} — WASD / Left Stick to move, Space / South Button to jump",
        "save_slot": f"{recipe.template_id}_{recipe.variant_id}_autosave",
        "locomotion_controller_asset_id": str(locomotion_controller_id),
        "rendering": {
            "upscaler": "native" if pixel else "tc_temporal", "quality": "native" if pixel else "quality",
            "output_width": 320 if visual_style == "pixel_8bit" else 1920,
            "output_height": 180 if visual_style == "pixel_8bit" else 1080,
            "sharpness": 0.0 if pixel else 0.18, "exposure": 1.05,
            "lighting_model": "toon" if toon else "physically_based",
            "global_illumination": "probe", "dynamic_diffuse_gi": not pixel,
            "sky_color": [0.12, 0.28, 0.58], "ground_color": [0.035, 0.05, 0.075],
            "atmosphere_enabled": not pixel, "target_frame_ms": 16.6667,
        },
        "simulation": {
            "domain": "everyday", "meters_per_world_unit": 1.0,
            "gravity_meters_per_second_squared": [0.0, -9.80665, 0.0],
            "fixed_timestep_seconds": 1.0 / 120.0, "maximum_substeps": 8,
            "floor_enabled": True, "contact_solver_iterations": 6,
        },
        "entities": [
            _player_entity(recipe, locomotion_controller_id, character),
            {
                "name": "Ground", "role": "walkable_surface",
                "transform": {"position": [0.0, -0.5, 2.0], "scale": [24.0, 1.0, 24.0]},
                "render": {"mesh": "builtin:cube", "base_color": [0.12, 0.16, 0.2], "roughness": 0.82},
                "collider": {"shape": "box", "half_extents": [12.0, 0.5, 12.0], "layer": 1},
            },
            {
                "name": "Ramp", "role": "walkable_surface",
                "transform": {"position": [4.0, 0.25, 3.5], "rotation": [0.0, 0.0, -12.0], "scale": [4.0, 0.5, 3.0]},
                "render": {"mesh": "builtin:cube", "base_color": [0.24, 0.34, 0.42], "roughness": 0.7},
                "collider": {"shape": "box", "half_extents": [2.0, 0.25, 1.5], "layer": 1},
            },
            {
                "name": "PhysicsCube", "role": "interactive_prop",
                "transform": {"position": [-3.0, 1.25, 3.0]},
                "render": {"mesh": "builtin:cube", "base_color": [0.92, 0.34, 0.08], "roughness": 0.46},
                "rigid_body": {"mass": 12.0, "dynamic": True, "continuous_collision": True},
                "collider": {"shape": "box", "half_extents": [0.5, 0.5, 0.5], "layer": 2},
            },
            {
                "name": "KillVolume", "role": "reset_volume",
                "transform": {"position": [0.0, -8.0, 0.0]},
                "collider": {"shape": "box", "half_extents": [30.0, 1.0, 30.0], "trigger": True, "layer": 8},
            },
            {
                "name": "RuntimeCamera", "role": "player_camera",
                "transform": {"position": camera_position},
                "camera": {"active": True, "field_of_view": 58.0, "look_at": [0.0, 1.0, 2.0], "mode": recipe.camera_mode},
            },
            {
                "name": "Sun", "role": "directional_light",
                "light": {"direction": [-0.45, -1.0, -0.3], "color": [1.0, 0.93, 0.78], "intensity": 4.5, "casts_shadow": True},
            },
        ],
        "begin_play": [
            {"node_id": "template_ready", "operation": "event.emit", "arguments": ["TemplateReady"]},
            {"node_id": "locomotion_idle", "operation": "animation.play", "arguments": ["tc_idle", "restart"]},
        ],
        "tick": [
            {"node_id": "player_move", "operation": "character.move", "arguments": [
                "Player", 5.5, 30.0, 38.0, 0.35, recipe.movement_mode,
            ]},
            {"node_id": "player_jump", "operation": "character.jump", "arguments": ["Player", 6.5, 0.1, 0.12]},
            {"node_id": "locomotion_animation", "operation": "animation.locomotion", "arguments": [
                "Player", "tc_idle", "tc_walk", "tc_walk_forward_right", "tc_walk_right",
                "tc_walk_backward_right", "tc_walk_backward", "tc_walk_backward_left", "tc_walk_left",
                "tc_walk_forward_left", "tc_run", "tc_jump", "tc_land", 0.15, 3.4, 0.16,
            ]},
            {"node_id": "camera_follow", "operation": "camera.follow", "arguments": [
                "RuntimeCamera", "Player", *({
                    "first_person": [0.0, 0.7, 0.05], "side": [0.0, 2.2, -12.0],
                    "fighting": [0.0, 2.4, -11.0], "third_person": [0.0, 3.2, -7.5],
                }[recipe.camera_mode]), 1.0, 5.0 if recipe.camera_mode == "first_person" else 0.0, 14.0,
            ]},
        ],
    }
    if recipe.movement_mode == "plane_2d":
        world["movement_constraints"] = {"player": "Player", "locked_axis": "z", "plane_origin": 0.0}
    return world


def _quality_for_style(visual_style: str) -> str:
    style = str(visual_style).casefold()
    if style in {"pixel_8bit", "pixel_16bit", "vector_flat", "low_poly"}:
        return "performance"
    if style in {"photoreal", "hyperreal"}:
        return "cinematic"
    return "high"


def _locomotion_preset_id(recipe: GameTemplateVariant) -> str:
    if recipe.camera_mode == "first_person":
        return "first_person"
    if recipe.camera_mode == "side":
        return "side_scroller"
    if recipe.camera_mode == "fighting":
        return "fighting"
    return "third_person"


def _safe_prefix(value: str) -> str:
    cleaned = "".join(character if character.isalnum() else "_" for character in str(value).strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    if not cleaned:
        raise ValueError("Project name must contain a letter or number.")
    return cleaned[:80]


def _issue(severity: str, code: str, message: str) -> dict[str, str]:
    return {"severity": severity, "code": code, "message": message}


__all__ = [
    "GAME_TEMPLATE_SCHEMA", "GAME_TEMPLATE_RECEIPT_SCHEMA", "PLAY_READINESS_SCHEMA",
    "GameTemplateReceipt", "GameTemplateService", "GameTemplateVariant",
    "available_game_templates", "resolve_game_template",
]
