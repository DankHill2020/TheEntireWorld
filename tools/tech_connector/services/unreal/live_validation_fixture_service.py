from __future__ import annotations

"""Disposable Unreal validation fixture plans for risky editor mutations."""

from dataclasses import dataclass, asdict
from typing import Any, Callable
import uuid


FixtureBuilder = Callable[[dict[str, Any]], dict[str, Any]]
_OPERATION_FIXTURE_BUILDERS: dict[str, FixtureBuilder] = {}


@dataclass(frozen=True)
class UnrealValidationFixture:
    id: str
    target_asset: str
    disposable_asset: str
    operations_under_test: tuple[str, ...]
    setup_operations: tuple[str, ...]
    validation_operations: tuple[str, ...]
    cleanup_operations: tuple[str, ...]
    rollback_operations: tuple[str, ...]
    python_script: str
    expected_evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_anim_blueprint_disposable_fixture(
    *,
    target_abp: str,
    state_machine_name: str,
    transitions: list[str],
    preserve_fixture_on_failure: bool = True,
) -> dict[str, Any]:
    """Return a concrete Unreal Python fixture that validates ABP graph mutation on a duplicate."""
    disposable_asset = "/Game/AIStudio/ValidationFixtures/ABP_DisposableValidation"
    transition_rows = _transition_rows(transitions)
    script = _anim_blueprint_fixture_script(
        target_abp=target_abp,
        disposable_asset=disposable_asset,
        state_machine_name=state_machine_name,
        transition_rows=transition_rows,
        preserve_fixture_on_failure=preserve_fixture_on_failure,
    )
    fixture = UnrealValidationFixture(
        id="anim_blueprint_disposable_transition_rule_fixture",
        target_asset=target_abp,
        disposable_asset=disposable_asset,
        operations_under_test=(
            "rollback.record_asset_snapshot",
            "anim_graph.add_transition_rule",
            "anim_graph.synthesize_transition_rule_expression",
            "blueprint.compile_and_save",
            "blueprint.scan",
        ),
        setup_operations=("asset.duplicate", "rollback.record_asset_snapshot", "blueprint.scan"),
        validation_operations=("blueprint.compile_and_save", "blueprint.scan"),
        cleanup_operations=("asset.delete",),
        rollback_operations=("rollback.restore_asset_snapshot",),
        python_script=script,
        expected_evidence=(
            "snapshot token recorded before mutation",
            "disposable AnimBlueprint duplicate created",
            "transition graph mutation returned ok:true",
            "compile/save returned ok:true",
            "post-mutation scan contains transition result graph evidence",
        ),
    )
    return fixture.to_dict()


def build_niagara_source_strategy_disposable_fixture(
    *,
    source_system: str,
    source_strategy: str,
    parameters: dict[str, Any] | None = None,
    preserve_fixture_on_failure: bool = True,
) -> dict[str, Any]:
    """Build a disposable fixture that requires Niagara mutation plus readback proof."""
    disposable_asset = "/Game/AIStudio/ValidationFixtures/NS_DisposableSourceStrategy"
    script = _niagara_source_strategy_fixture_script(
        source_system=source_system,
        disposable_asset=disposable_asset,
        source_strategy=source_strategy,
        parameters=dict(parameters or {}),
        preserve_fixture_on_failure=preserve_fixture_on_failure,
    )
    return UnrealValidationFixture(
        id="niagara_disposable_source_strategy_fixture",
        target_asset=source_system,
        disposable_asset=disposable_asset,
        operations_under_test=("niagara.synthesize_source_strategy_stack", "niagara.inspect_system"),
        setup_operations=("asset.duplicate", "niagara.inspect_system"),
        validation_operations=("niagara.synthesize_source_strategy_stack", "niagara.inspect_system", "asset.save"),
        cleanup_operations=("asset.delete",),
        rollback_operations=("asset.delete",),
        python_script=script,
        expected_evidence=(
            "disposable Niagara System duplicate created",
            f"source strategy {source_strategy} reported as applied",
            "module or renderer stack readback is non-empty",
            "requested parameters report accepted or rejected status",
            "disposable system saved and reloaded",
        ),
    ).to_dict()


def build_pose_search_disposable_fixture(
    *,
    skeleton_path: str,
    animation_path: str,
) -> dict[str, Any]:
    suffix = uuid.uuid4().hex[:8]
    schema_path = f"/Game/AIStudio/ValidationFixtures/PS_Schema_{suffix}"
    database_path = f"/Game/AIStudio/ValidationFixtures/PSD_Database_{suffix}"
    script = f"""import json
import unreal

skeleton_path = {skeleton_path!r}
animation_path = {animation_path!r}
schema_path = {schema_path!r}
database_path = {database_path!r}
steps = []
errors = []

def run(name, value):
    row = json.loads(value)
    steps.append({{"operation": name, "result": row}})
    if not row.get("ok"):
        errors.append({{"operation": name, "result": row}})
    return row

schema = run("motion_matching.create_schema", unreal.AIStudioBridgeLibrary.create_pose_search_schema(
    skeleton_path, schema_path, 30
))
channel = run("motion_matching.add_schema_channel", unreal.AIStudioBridgeLibrary.add_pose_search_schema_channel(
    schema_path,
    "/Script/PoseSearch.PoseSearchFeatureChannel_Position",
    "{{}}",
))
database = run("motion_matching.create_database", unreal.AIStudioBridgeLibrary.create_pose_search_database(
    schema_path, database_path
))
animation = run("motion_matching.add_animation", unreal.AIStudioBridgeLibrary.add_pose_search_animation(
    database_path, animation_path
))
ok = bool(
    not errors
    and int(channel.get("channel_count") or 0) >= 1
    and int(animation.get("animation_count") or 0) >= 1
    and unreal.EditorAssetLibrary.does_asset_exist(schema_path)
    and unreal.EditorAssetLibrary.does_asset_exist(database_path)
)
print(json.dumps({{
    "ok": ok,
    "schema_path": schema_path,
    "database_path": database_path,
    "steps": steps,
    "errors": errors,
}}, indent=2))
"""
    cleanup_script = f"""import json
import unreal
paths = [{database_path!r}, {schema_path!r}]
deleted = {{}}
for path in paths:
    existed = bool(unreal.EditorAssetLibrary.does_asset_exist(path))
    deleted[path] = bool(unreal.EditorAssetLibrary.delete_asset(path)) if existed else True
remaining = [path for path in paths if unreal.EditorAssetLibrary.does_asset_exist(path)]
print(json.dumps({{"ok": not remaining and all(deleted.values()), "deleted": deleted, "remaining": remaining}}))
"""
    fixture = UnrealValidationFixture(
        id="pose_search_disposable_database_fixture",
        target_asset=skeleton_path,
        disposable_asset=database_path,
        operations_under_test=(
            "motion_matching.create_schema",
            "motion_matching.add_schema_channel",
            "motion_matching.create_database",
            "motion_matching.add_animation",
        ),
        setup_operations=("asset.validate_skeleton", "asset.validate_animation_compatibility"),
        validation_operations=("asset.save", "asset.channel_readback", "asset.animation_readback"),
        cleanup_operations=("asset.delete_database", "asset.delete_schema"),
        rollback_operations=("asset.delete_database", "asset.delete_schema"),
        python_script=script,
        expected_evidence=(
            "schema exists with at least one concrete feature channel",
            "database exists and references the schema",
            "compatible animation count is at least one",
            "both disposable assets are removed after validation",
        ),
    ).to_dict()
    fixture["cleanup_python_script"] = cleanup_script
    fixture["related_disposable_assets"] = [schema_path, database_path]
    return fixture


def build_physics_asset_disposable_fixture(
    *,
    skeletal_mesh_path: str,
    test_bone: str,
) -> dict[str, Any]:
    suffix = uuid.uuid4().hex[:8]
    physics_asset_path = f"/Game/AIStudio/ValidationFixtures/PHYS_Disposable_{suffix}"
    script = f"""import json
import unreal

skeletal_mesh_path = {skeletal_mesh_path!r}
physics_asset_path = {physics_asset_path!r}
test_bone = {test_bone!r}
steps = []
errors = []

def run(name, value):
    row = json.loads(value)
    steps.append({{"operation": name, "result": row}})
    if not row.get("ok"):
        errors.append({{"operation": name, "result": row}})
    return row

created = run("physics.create_physics_asset", unreal.AIStudioBridgeLibrary.create_physics_asset(
    skeletal_mesh_path, physics_asset_path, False
))
body = run("physics.add_body", unreal.AIStudioBridgeLibrary.add_physics_body(
    physics_asset_path, unreal.Name(test_bone), "sphere"
))
inspected = run("physics.inspect", unreal.AIStudioBridgeLibrary.inspect_physics_asset(
    physics_asset_path
))
profile = run("physics.add_profile", unreal.AIStudioBridgeLibrary.add_physics_profile(
    physics_asset_path, unreal.Name("AIStudio_Disposable"), "constraint", True
))
profiles = run("physics.list_profiles", unreal.AIStudioBridgeLibrary.list_physics_profiles(
    physics_asset_path
))
ok = bool(
    not errors
    and any(row.get("bone_name") == test_bone for row in inspected.get("bodies") or [])
    and any(
        row.get("name") == "AIStudio_Disposable"
        for row in profiles.get("constraint_profiles") or []
    )
)
print(json.dumps({{
    "ok": ok,
    "physics_asset_path": physics_asset_path,
    "steps": steps,
    "errors": errors,
}}, indent=2))
"""
    cleanup_script = f"""import json
import unreal
path = {physics_asset_path!r}
existed = bool(unreal.EditorAssetLibrary.does_asset_exist(path))
deleted = bool(unreal.EditorAssetLibrary.delete_asset(path)) if existed else True
remaining = bool(unreal.EditorAssetLibrary.does_asset_exist(path))
print(json.dumps({{"ok": deleted and not remaining, "existed": existed, "deleted": deleted, "remaining": remaining}}))
"""
    fixture = UnrealValidationFixture(
        id="physics_asset_disposable_body_profile_fixture",
        target_asset=skeletal_mesh_path,
        disposable_asset=physics_asset_path,
        operations_under_test=(
            "physics.create_physics_asset",
            "physics.add_body",
            "physics.inspect",
            "physics.add_profile",
            "physics.list_profiles",
        ),
        setup_operations=("asset.validate_skeletal_mesh", "asset.validate_bone"),
        validation_operations=("asset.body_readback", "asset.profile_readback", "asset.save"),
        cleanup_operations=("asset.delete",),
        rollback_operations=("asset.delete",),
        python_script=script,
        expected_evidence=(
            "noninteractive PhysicsAsset creation succeeds",
            "requested bone body is present in native readback",
            "constraint profile assignment count is nonzero",
            "disposable PhysicsAsset is removed after validation",
        ),
    ).to_dict()
    fixture["cleanup_python_script"] = cleanup_script
    return fixture


def register_operation_fixture_builder(operation: str, builder: FixtureBuilder) -> None:
    """Register executable disposable proof without coupling callers to a domain."""

    _OPERATION_FIXTURE_BUILDERS[str(operation or "").strip()] = builder


def build_operation_disposable_fixture(
    operation: str,
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build a registered disposable fixture for an operation when one exists."""

    builder = _OPERATION_FIXTURE_BUILDERS.get(str(operation or "").strip())
    return dict(builder(dict(context or {})) or {}) if builder is not None else None


def _build_niagara_source_strategy_from_context(context: dict[str, Any]) -> dict[str, Any]:
    arguments = dict(context.get("arguments") or {})
    contract = dict(context.get("behavior_contract") or {})
    return build_niagara_source_strategy_disposable_fixture(
        source_system=str(
            arguments.get("source_system_path")
            or "/Game/Variant_Platforming/VFX/NS_Jump_Trail"
        ),
        source_strategy=str(contract.get("source_strategy") or ""),
        parameters=dict(arguments.get("parameters") or {}),
    )


def _build_blendspace_from_context(context: dict[str, Any]) -> dict[str, Any]:
    arguments = dict(context.get("arguments") or {})
    skeleton_path = str(
        arguments.get("skeleton_path")
        or arguments.get("target_skeleton_path")
        or ""
    )
    disposable_asset = (
        "/Game/AIStudio/ValidationFixtures/"
        f"BS_DisposableValidation_{uuid.uuid4().hex[:8]}"
    )
    script = f"""import json
import unreal
from unreal_tools.animation import create_blendspace

skeleton_path = {skeleton_path!r}
fixture_path = {disposable_asset!r}
result = {{"ok": False, "fixture_path": fixture_path, "steps": [], "errors": []}}
if not skeleton_path or not unreal.EditorAssetLibrary.does_asset_exist(skeleton_path):
    result["errors"].append({{"status": "skeleton_not_found", "skeleton_path": skeleton_path}})
    print(json.dumps(result, indent=2))
    raise SystemExit
registry = unreal.AssetRegistryHelpers.get_asset_registry()
animation_path = ""
anim_sequence_class = unreal.TopLevelAssetPath("/Script/Engine", "AnimSequence")
for asset_data in registry.get_assets_by_class(anim_sequence_class, True):
    animation = asset_data.get_asset()
    try:
        compatible = bool(animation and animation.get_editor_property("skeleton") == unreal.EditorAssetLibrary.load_asset(skeleton_path))
    except Exception:
        compatible = False
    if compatible:
        animation_path = str(animation.get_path_name())
        break
if not animation_path:
    result["errors"].append({{"status": "compatible_animation_not_found"}})
    print(json.dumps(result, indent=2))
    raise SystemExit
created = json.loads(create_blendspace(
    fixture_path,
    skeleton_path,
    samples=[{{"animation_path": animation_path, "position": [0.0, 0.0, 0.0]}}],
    save=True,
))
result["steps"].append(created)
result["ok"] = bool(
    created.get("ok")
    and created.get("sample_authoring_status") == "validated_readback"
    and int(created.get("sample_count") or 0) >= 1
    and unreal.EditorAssetLibrary.does_asset_exist(fixture_path)
)
if not result["ok"]:
    result["errors"].append(created)
print(json.dumps(result, indent=2))
"""
    fixture = UnrealValidationFixture(
        id="blendspace_disposable_sample_authoring_fixture",
        target_asset=skeleton_path,
        disposable_asset=disposable_asset,
        operations_under_test=("unreal.create_blendspace",),
        setup_operations=("asset.find_compatible_animation",),
        validation_operations=(
            "unreal.create_blendspace",
            "asset.sample_readback",
            "asset.save",
        ),
        cleanup_operations=("asset.delete",),
        rollback_operations=("asset.delete",),
        python_script=script,
        expected_evidence=(
            "target Skeleton exists",
            "compatible AnimSequence is discovered",
            "BlendSpace is created and saved",
            "at least one authored sample is read back as valid",
            "disposable BlendSpace is deleted",
        ),
    ).to_dict()
    fixture["cleanup_python_script"] = f"""import json
import unreal
fixture_path = {disposable_asset!r}
existed = bool(unreal.EditorAssetLibrary.does_asset_exist(fixture_path))
deleted = bool(unreal.EditorAssetLibrary.delete_asset(fixture_path)) if existed else True
remaining = bool(unreal.EditorAssetLibrary.does_asset_exist(fixture_path))
print(json.dumps({{"ok": deleted and not remaining, "existed": existed, "deleted": deleted, "remaining": remaining}}))
"""
    return fixture


def _build_pose_search_from_context(context: dict[str, Any]) -> dict[str, Any]:
    arguments = dict(context.get("arguments") or {})
    return build_pose_search_disposable_fixture(
        skeleton_path=str(arguments.get("skeleton_path") or ""),
        animation_path=str(
            arguments.get("animation_path")
            or next(iter(arguments.get("animation_paths") or []), "")
        ),
    )


def _build_physics_asset_from_context(context: dict[str, Any]) -> dict[str, Any]:
    arguments = dict(context.get("arguments") or {})
    return build_physics_asset_disposable_fixture(
        skeletal_mesh_path=str(arguments.get("skeletal_mesh_path") or ""),
        test_bone=str(arguments.get("test_bone") or arguments.get("bone_name") or "pelvis"),
    )


register_operation_fixture_builder(
    "niagara.synthesize_source_strategy_stack",
    _build_niagara_source_strategy_from_context,
)
register_operation_fixture_builder(
    "unreal.create_blendspace",
    _build_blendspace_from_context,
)
register_operation_fixture_builder(
    "motion_matching.create_database",
    _build_pose_search_from_context,
)
register_operation_fixture_builder(
    "physics.create_physics_asset",
    _build_physics_asset_from_context,
)


def _transition_rows(transitions: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in transitions:
        text = str(item or "")
        condition = "true"
        left = text
        if " when " in text:
            left, _, condition = text.partition(" when ")
        if "->" in left:
            from_state, _, to_state = left.partition("->")
        elif " to " in left:
            from_state, _, to_state = left.partition(" to ")
        else:
            from_state, to_state = "Locomotion", "RequestedState"
        rows.append(
            {
                "from_state": from_state.strip() or "Locomotion",
                "to_state": to_state.strip() or "RequestedState",
                "rule_expression": condition.strip() or "true",
            }
        )
    return rows


def _anim_blueprint_fixture_script(
    *,
    target_abp: str,
    disposable_asset: str,
    state_machine_name: str,
    transition_rows: list[dict[str, str]],
    preserve_fixture_on_failure: bool,
) -> str:
    rows_repr = repr(transition_rows)
    return f"""import json
import unreal
from unreal_tools import rollback

target_abp_path = {target_abp!r}
fixture_abp_path = {disposable_asset!r}
state_machine_name = {state_machine_name!r}
transitions = {rows_repr}
preserve_fixture_on_failure = {preserve_fixture_on_failure!r}

result = {{
    "ok": False,
    "target_abp_path": target_abp_path,
    "fixture_abp_path": fixture_abp_path,
    "steps": [],
    "errors": [],
}}

snapshot = json.loads(rollback.record_asset_snapshot(
    target_abp_path,
    reason="pre-disposable-validation baseline",
    operation="validation.anim_blueprint_disposable_fixture",
))
result["rollback_snapshot"] = snapshot
if not snapshot.get("ok"):
    result["errors"].append(snapshot)
    print(json.dumps(result, indent=2))
    raise SystemExit

if unreal.EditorAssetLibrary.does_asset_exist(fixture_abp_path):
    unreal.EditorAssetLibrary.delete_asset(fixture_abp_path)
fixture = unreal.EditorAssetLibrary.duplicate_asset(target_abp_path, fixture_abp_path)
if not fixture:
    result["errors"].append({{"status": "fixture_duplicate_failed"}})
    print(json.dumps(result, indent=2))
    raise SystemExit
result["steps"].append({{"operation": "asset.duplicate", "ok": True}})

for row in transitions:
    add_raw = unreal.AIStudioBridgeLibrary.add_anim_graph_transition_rule(
        fixture,
        state_machine_name,
        row["from_state"],
        row["to_state"],
        "true",
    )
    add_result = json.loads(add_raw)
    result["steps"].append(add_result)
    synth_raw = unreal.AIStudioBridgeLibrary.synthesize_anim_graph_transition_rule_expression(
        fixture,
        state_machine_name,
        row["from_state"],
        row["to_state"],
        row["rule_expression"],
    )
    synth_result = json.loads(synth_raw)
    result["steps"].append(synth_result)
    if not synth_result.get("ok"):
        result["errors"].append(synth_result)

compile_result = json.loads(unreal.AIStudioBridgeLibrary.compile_and_save_anim_blueprint(fixture))
result["steps"].append(compile_result)
scan_result = json.loads(unreal.AIStudioBridgeLibrary.inspect_anim_blueprint_graph(fixture))
result["steps"].append(scan_result)
result["ok"] = compile_result.get("ok") and scan_result.get("ok") and not result["errors"]

if result["ok"] or not preserve_fixture_on_failure:
    unreal.EditorAssetLibrary.delete_asset(fixture_abp_path)
    result["steps"].append({{"operation": "asset.delete_fixture", "ok": True}})
else:
    result["fixture_preserved_for_debug"] = fixture_abp_path

print(json.dumps(result, indent=2))
"""




def _niagara_source_strategy_fixture_script(
    *,
    source_system: str,
    disposable_asset: str,
    source_strategy: str,
    parameters: dict[str, Any],
    preserve_fixture_on_failure: bool,
) -> str:
    return f"""import json
import unreal
from unreal_tools import niagara

source_system = {source_system!r}
fixture_system = {disposable_asset!r}
source_strategy = {source_strategy!r}
parameters = {parameters!r}
preserve_fixture_on_failure = {preserve_fixture_on_failure!r}
result = {{"ok": False, "steps": [], "errors": [], "fixture_system": fixture_system}}

if unreal.EditorAssetLibrary.does_asset_exist(fixture_system):
    unreal.EditorAssetLibrary.delete_asset(fixture_system)
fixture = unreal.EditorAssetLibrary.duplicate_asset(source_system, fixture_system)
if not fixture:
    result["errors"].append({{"status": "fixture_duplicate_failed", "source_system": source_system}})
    print(json.dumps(result, indent=2))
    raise SystemExit
result["steps"].append({{"operation": "asset.duplicate", "ok": True}})

mutation = json.loads(niagara.synthesize_source_strategy_stack(
    system_path=fixture_system,
    source_strategy=source_strategy,
    parameters=parameters,
    save=True,
))
result["steps"].append(mutation)
readback = json.loads(niagara.inspect_system(fixture_system))
result["steps"].append(readback)

stack_readback = mutation.get("stack_readback") or mutation.get("module_readback") or mutation.get("renderer_readback")
strategy_applied = mutation.get("source_strategy") == source_strategy or mutation.get("source_strategy_applied") == source_strategy
parameters_reported = "parameters_applied" in mutation or "parameters_rejected" in mutation
reloaded = unreal.EditorAssetLibrary.load_asset(fixture_system)
result["ok"] = bool(mutation.get("ok") and readback.get("ok") and stack_readback and strategy_applied and parameters_reported and reloaded)
if not result["ok"]:
    result["errors"].append({{
        "status": "behavior_readback_failed",
        "strategy_applied": strategy_applied,
        "stack_readback": stack_readback,
        "parameters_reported": parameters_reported,
        "reloaded": bool(reloaded),
    }})

if result["ok"] or not preserve_fixture_on_failure:
    unreal.EditorAssetLibrary.delete_asset(fixture_system)
    result["steps"].append({{"operation": "asset.delete_fixture", "ok": True}})
else:
    result["fixture_preserved_for_debug"] = fixture_system

print(json.dumps(result, indent=2, default=str))
"""
