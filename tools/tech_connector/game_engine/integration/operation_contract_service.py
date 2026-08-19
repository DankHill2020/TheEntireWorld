from __future__ import annotations

"""Unified, typed contracts for planner-visible host operations.

The host registries and Unreal capability inventory remain authoritative for
what is callable. This module adds the artifact semantics needed to compose
those callables without maintaining a second list of operations.
"""

from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any, Iterable

from tech_connector.game_engine.integration.dcc_operation_service import dcc_operation_registry


HOSTS = (
    "maya",
    "blender",
    "motionbuilder",
    "houdini",
    "substance_painter",
    "unity",
    "unreal",
)


@dataclass(frozen=True)
class OperationContract:
    key: str
    host: str
    operation: str
    label: str
    callable: str
    provider: str = "registered_operation"
    role: str = "operate"
    phase_order: int = 0
    formats: tuple[str, ...] = ()
    subjects: tuple[str, ...] = ("asset",)
    consumes: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    required: tuple[str, ...] = ()
    optional: dict[str, Any] = field(default_factory=dict)
    preconditions: tuple[str, ...] = ()
    validation: tuple[str, ...] = ()
    rollback: tuple[str, ...] = ()
    mutates_project: bool = False
    implementation_state: str = "implemented"
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def executable(self) -> bool:
        return self.implementation_state in {
            "implemented",
            "implemented_python",
            "implemented_cpp_bridge",
            "cpp_preferred_with_context_readback",
        } and bool(self.callable)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["executable"] = self.executable
        return result


# Artifact semantics are annotations on canonical operations, not another
# callable registry. Adding an operation to a host registry makes it searchable
# immediately; add an override only when it participates in typed composition.
_TRANSFER_OVERRIDES: dict[tuple[str, str], dict[str, Any]] = {
    ("maya", "pipeline.create_rigged_proxy"): {
        "role": "prepare",
        "subjects": ("animation", "skeletal_mesh"),
        "produces": (
            "maya_scene",
            "mesh",
            "root_joint",
            "joints",
            "frame_range",
            "selection",
        ),
        "validation": (
            "created mesh, joints, skin cluster, animation range, and selection are reported",
        ),
        "rollback": ("delete the reported disposable fixture group",),
    },
    ("maya", "animation.export"): {
        "role": "export",
        "formats": ("fbx",),
        "subjects": ("animation", "skeletal_mesh"),
        "consumes": ("maya_scene",),
        "produces": ("fbx_path",),
        "validation": ("export file exists",),
    },
    ("blender", "io.import_fbx"): {
        "role": "import",
        "formats": ("fbx",),
        "subjects": ("asset", "animation", "static_mesh", "skeletal_mesh"),
        "consumes": ("fbx_path",),
        "produces": ("blender_scene", "meshes", "armatures", "animations"),
        "validation": ("imported object count is reported",),
    },
    ("blender", "blender.clean_animation"): {
        "role": "process",
        "subjects": ("animation",),
        "consumes": ("animations",),
        "produces": ("animations",),
        "validation": ("processed actions and frame range are reported",),
    },
    ("blender", "pipeline.process_meshes_for_transfer"): {
        "role": "process",
        "subjects": ("asset", "static_mesh", "skeletal_mesh"),
        "consumes": ("blender_scene",),
        "produces": (
            "blender_scene",
            "meshes",
            "materials",
            "collision",
            "lods",
        ),
        "validation": (
            "processed mesh names, transforms, LODs, materials, and collision are reported",
        ),
        "rollback": ("discard unsaved Blender scene changes or remove reported objects",),
    },
    ("blender", "blender.export_fbx"): {
        "role": "export",
        "formats": ("fbx",),
        "subjects": ("asset", "animation", "static_mesh", "skeletal_mesh"),
        "consumes": ("blender_scene",),
        "produces": ("fbx_path",),
        "validation": ("export file exists",),
    },
    ("blender", "io.export_fbx"): {
        "role": "export",
        "formats": ("fbx",),
        "subjects": ("asset", "animation", "static_mesh", "skeletal_mesh"),
        "consumes": ("blender_scene",),
        "produces": ("fbx_path",),
        "validation": ("export file exists",),
    },
    ("motionbuilder", "io.import_fbx"): {
        "role": "import",
        "formats": ("fbx",),
        "subjects": ("animation", "skeletal_mesh"),
        "consumes": ("fbx_path",),
        "produces": ("motionbuilder_scene", "animations", "skeleton"),
        "validation": ("scene take and model counts are reported",),
    },
    ("motionbuilder", "io.export_fbx"): {
        "role": "export",
        "formats": ("fbx",),
        "subjects": ("animation", "skeletal_mesh"),
        "consumes": ("motionbuilder_scene",),
        "produces": ("fbx_path",),
        "validation": ("export file exists",),
    },
    ("houdini", "geometry.import"): {
        "role": "import",
        "formats": ("fbx", "abc", "usd"),
        "subjects": ("asset", "static_mesh"),
        "consumes": ("transfer_path",),
        "produces": ("houdini_geometry",),
    },
    ("houdini", "geometry.export"): {
        "role": "export",
        "formats": ("fbx", "abc"),
        "subjects": ("asset", "static_mesh"),
        "consumes": ("houdini_geometry",),
        "produces": ("transfer_path",),
        "validation": ("export file exists",),
    },
    ("houdini", "usd.export"): {
        "role": "export",
        "formats": ("usd",),
        "subjects": ("asset", "static_mesh"),
        "consumes": ("houdini_geometry",),
        "produces": ("usd_path",),
        "validation": ("USD file exists",),
    },
    ("substance_painter", "textures.export"): {
        "role": "export",
        "formats": ("textures",),
        "subjects": ("textures", "material"),
        "consumes": ("substance_project",),
        "produces": ("texture_paths",),
        "validation": ("exported texture paths exist",),
    },
    ("unity", "assets.import_fbx"): {
        "role": "import",
        "formats": ("fbx",),
        "subjects": ("asset", "animation", "static_mesh", "skeletal_mesh"),
        "consumes": ("fbx_path",),
        "produces": ("unity_asset_path",),
        "validation": ("imported asset resolves in AssetDatabase",),
    },
    ("unreal", "animation.inspect_imported_pipeline"): {
        "role": "post_import",
        "phase_order": 10,
        "subjects": ("animation",),
        "consumes": ("imported_paths", "skeleton_path"),
        "produces": ("compatibility_report", "animation_paths"),
        "validation": (
            "frame, duration, root motion, skeleton, and compatibility evidence are reported",
        ),
    },
    ("unreal", "animation.resolve_target"): {
        "role": "resolve",
        "subjects": ("animation", "skeletal_mesh"),
        "produces": (
            "target_skeletal_mesh_path",
            "target_skeleton_path",
            "target_anim_blueprint_path",
        ),
        "validation": ("target mesh, Skeleton, and existing AnimBlueprint are reported",),
    },
    ("unreal", "asset.import_fbx_verified"): {
        "role": "import",
        "formats": ("fbx",),
        "subjects": ("asset", "animation", "static_mesh", "skeletal_mesh"),
        "consumes": ("source_file", "destination_path", "skeleton_path"),
        "produces": ("asset_path", "imported_paths", "asset_count"),
        "validation": ("imported object paths resolve in EditorAssetLibrary",),
        "rollback": ("unreal_tools.asset_transfer_adapter.rollback_imported_assets",),
    },
    ("unreal", "animation.import_verified"): {
        "role": "import",
        "formats": ("fbx",),
        "subjects": ("animation",),
        "consumes": ("anim_path", "skeleton_path", "destination_path"),
        "produces": ("asset_path", "imported_paths"),
        "validation": ("animation import returns paths that resolve in EditorAssetLibrary",),
        "rollback": ("unreal_tools.asset_transfer_adapter.rollback_imported_assets",),
    },
    ("unreal", "asset.registry_readback"): {
        "role": "validate",
        "subjects": ("asset", "animation", "static_mesh", "skeletal_mesh"),
        "consumes": ("imported_paths",),
        "produces": ("assets", "asset_count"),
        "validation": ("all imported paths resolve in the Asset Registry",),
    },
    ("unreal", "animation.retarget_imported_if_needed"): {
        "role": "post_import",
        "phase_order": 20,
        "subjects": ("animation",),
        "consumes": ("compatibility_report",),
        "produces": ("animation_paths", "retarget_report"),
        "validation": ("compatible animations are preserved and incompatible animations are retargeted",),
        "rollback": ("delete only newly reported retargeted assets",),
    },
    ("unreal", "unreal.create_blendspace"): {
        "role": "post_import",
        "phase_order": 30,
        "subjects": ("animation",),
        "consumes": ("animation_paths", "skeleton_path"),
        "produces": ("blendspace_path",),
        "validation": ("BlendSpace asset and sample readback are returned",),
        "rollback": ("delete the newly reported BlendSpace asset",),
        "implementation_state": "requires_live_validation",
    },
    ("unreal", "animation.create_anim_bp"): {
        "role": "author",
        "subjects": ("animation",),
        "consumes": ("skeleton_path",),
        "produces": ("anim_bp_path",),
        "validation": ("AnimBlueprint exists, targets the requested Skeleton, compiles, and saves",),
        "rollback": ("delete the newly reported AnimBlueprint when created by this run",),
    },
    ("unreal", "animation.report_pipeline_assets"): {
        "role": "post_import",
        "phase_order": 100,
        "subjects": ("animation",),
        "consumes": ("imported_paths", "animation_paths", "skeleton_path"),
        "produces": ("pipeline_report",),
        "validation": ("final asset existence, save state, Skeleton, and AnimBlueprint evidence are returned",),
    },
}

_CALLABLE_OVERRIDES: dict[str, dict[str, Any]] = {
    "unreal_tools.asset_transfer_adapter.import_fbx_verified": {
        "role": "import",
        "formats": ("fbx",),
        "subjects": ("asset", "animation", "static_mesh", "skeletal_mesh"),
        "consumes": ("fbx_path", "destination_path"),
        "produces": ("asset_path", "imported_paths", "asset_count"),
        "required": ("source_file",),
        "optional": {
            "destination_path": "/Game/AIStudio/Imports",
            "subject": "asset",
            "skeleton_path": "",
            "replace_existing": False,
            "save": True,
        },
        "validation": ("imported object paths resolve in EditorAssetLibrary",),
        "rollback": (
            "unreal_tools.asset_transfer_adapter.rollback_imported_assets",
        ),
        "mutates_project": True,
    },
    "unreal_tools.asset_transfer_adapter.registry_readback": {
        "role": "validate",
        "subjects": ("asset", "animation", "static_mesh", "skeletal_mesh"),
        "consumes": ("imported_paths",),
        "produces": ("assets", "asset_count"),
        "required": (),
        "optional": {"imported_paths": [], "destination_path": ""},
        "validation": ("all requested paths resolve in Asset Registry",),
    },
    "unreal_tools.animation_import_adapter.import_animation_verified": {
        "role": "import",
        "formats": ("fbx",),
        "subjects": ("animation",),
        "consumes": ("fbx_path", "skeleton_path"),
        "produces": ("asset_path", "imported_paths"),
        "validation": ("animation import returns structured asset paths",),
        "mutates_project": True,
    },
}


def _normalize_registered(host: str, key: str, operation: Any) -> OperationContract:
    override = dict(_TRANSFER_OVERRIDES.get((host, key), {}))
    description = str(getattr(operation, "description", "") or "")
    implementation_state = str(
        override.pop(
            "implementation_state",
            getattr(operation, "implementation_state", "implemented"),
        )
        or "implemented"
    )
    implementation_evidence = tuple(
        getattr(operation, "implementation_evidence", ()) or ()
    )
    validation_receipt: dict[str, Any] = {}
    try:
        from tech_connector.game_engine.integration.operation_evidence_service import (
            operation_validation_receipt,
        )

        validation_receipt = operation_validation_receipt(key)
    except Exception:
        validation_receipt = {}
    if implementation_state not in {
        "implemented",
        "implemented_python",
        "implemented_cpp_bridge",
        "cpp_preferred_with_context_readback",
    }:
        if validation_receipt.get("ok"):
            implementation_state = "implemented_cpp_bridge"
    evidence_level = (
        "live_validated"
        if validation_receipt.get("ok")
        else "declared_implementation_evidence"
        if implementation_evidence
        else "registered_callable"
    )
    produces = tuple(override.pop("produces", ()))
    if not produces and not bool(getattr(operation, "mutates_project", False)):
        produces = ("result",)
    return OperationContract(
        key=f"{host}.operations.{key}",
        host=host,
        operation=key,
        label=str(getattr(operation, "label", key) or key),
        callable=str(getattr(operation, "function", "") or ""),
        required=tuple(getattr(operation, "required", ()) or ()),
        optional=dict(getattr(operation, "optional", {}) or {}),
        mutates_project=bool(getattr(operation, "mutates_project", False)),
        implementation_state=implementation_state,
        source=f"tech_connector.game_engine.integration.dcc_operation_service:{host}",
        produces=produces,
        metadata={
            "description": description,
            "implementation_evidence": list(implementation_evidence),
            "validation_receipt": validation_receipt,
            "evidence_level": evidence_level,
            "live_validated": evidence_level == "live_validated",
        },
        **override,
    )


def _normalize_unreal_inventory(section: str, key: str, row: dict[str, Any]) -> OperationContract:
    implementation_state = str(row.get("implementation_state") or "implemented")
    callable_name = str(row.get("python_call") or row.get("function") or row.get("operation") or "")
    provider = {
        "plugin_functions": "unreal_plugin",
        "unreal_tools_functions": "unreal_tools",
        "capabilities": "unreal_capability",
        "cpp_domain_wrapper_requirements": "unreal_cpp_requirement",
    }.get(section, f"unreal_{section}")
    override = dict(_CALLABLE_OVERRIDES.get(callable_name, {}))
    required = tuple(override.pop("required", row.get("required") or ()))
    optional = dict(override.pop("optional", row.get("optional") or {}))
    mutates_project = bool(
        override.pop("mutates_project", row.get("mutates_project", False))
    )
    role = str(override.pop("role", "operate"))
    return OperationContract(
        key=f"unreal.{section}.{key}",
        host="unreal",
        operation=str(row.get("operation") or row.get("name") or key),
        label=str(row.get("label") or row.get("name") or key),
        callable=callable_name,
        provider=provider,
        role=role,
        required=required,
        optional=optional,
        mutates_project=mutates_project,
        implementation_state=implementation_state,
        source=str(row.get("source") or ""),
        metadata={k: v for k, v in row.items() if k not in {"required", "optional"}},
        **override,
    )


@lru_cache(maxsize=8)
def build_operation_contract_inventory(project_root: str | None = None) -> dict[str, Any]:
    contracts: dict[str, OperationContract] = {}
    host_counts: dict[str, int] = {}
    for host in HOSTS:
        registry = dcc_operation_registry(host)
        host_counts[host] = len(registry)
        for key, operation in registry.items():
            contract = _normalize_registered(host, key, operation)
            contracts[contract.key] = contract

    from tech_connector.services.unreal.unreal_capability_inventory_service import (
        build_unreal_capability_inventory,
    )

    unreal = build_unreal_capability_inventory(project_root)
    # Registered operations are already present above. These sections add the
    # plugin, unreal_tools, capability, and wrapper surfaces without duplicates.
    for section in (
        "plugin_functions",
        "unreal_tools_functions",
        "capabilities",
        "cpp_domain_wrapper_requirements",
    ):
        for key, row in (unreal.get(section) or {}).items():
            contract = _normalize_unreal_inventory(section, key, row)
            contracts[contract.key] = contract

    return {
        "contracts": contracts,
        "host_operation_counts": host_counts,
        "unreal_counts": dict(unreal.get("counts") or {}),
        "materialized_count": len(contracts),
        "total_callable_surface": sum(
            count for host, count in host_counts.items() if host != "unreal"
        )
        + int((unreal.get("counts") or {}).get("total_callable_surface") or 0),
        "lazy_providers": {
            "unreal_python_api": int(
                (unreal.get("counts") or {}).get("base_unreal_python_api") or 0
            )
        },
    }


def operation_contracts(
    *,
    host: str = "",
    role: str = "",
    format: str = "",
    subject: str = "",
    project_root: str | None = None,
) -> list[OperationContract]:
    rows: Iterable[OperationContract] = build_operation_contract_inventory(project_root)[
        "contracts"
    ].values()
    result = []
    for contract in rows:
        if host and contract.host != host:
            continue
        if role and contract.role != role:
            continue
        if format and format not in contract.formats:
            continue
        if subject and subject != "asset" and subject not in contract.subjects:
            continue
        result.append(contract)
    return sorted(result, key=lambda item: (item.host, item.role, item.operation, item.key))


def resolve_operation_contract(
    query: str,
    *,
    host: str = "",
    project_root: str | None = None,
) -> dict[str, Any]:
    normalized = str(query or "").strip()
    inventory = build_operation_contract_inventory(project_root)
    candidates = []
    for contract in inventory["contracts"].values():
        if host and contract.host != host:
            continue
        searchable = {
            contract.key,
            contract.operation,
            contract.callable,
            contract.label,
        }
        if normalized in searchable or normalized.lower() in {
            value.lower() for value in searchable if value
        }:
            candidates.append(contract)
    if candidates:
        ordered = sorted(
            candidates,
            key=lambda item: (
                item.operation != normalized,
                item.provider != "registered_operation",
                item.key,
            ),
        )
        return {
            "ok": True,
            "contract": ordered[0].to_dict(),
            "alternates": [item.to_dict() for item in ordered[1:10]],
        }

    if not host or host == "unreal":
        from tech_connector.services.unreal.unreal_capability_inventory_service import (
            resolve_unreal_inventory_item,
        )

        resolved = resolve_unreal_inventory_item(normalized, project_root)
        if resolved.get("ok") and resolved.get("item"):
            row = dict(resolved["item"])
            section = str(resolved.get("section") or "base_unreal_python_api")
            contract = _normalize_unreal_inventory(section, normalized, row)
            return {"ok": True, "contract": contract.to_dict(), "alternates": []}
    return {"ok": False, "query": normalized, "host": host, "reason": "No verified callable matched."}


def transfer_contracts() -> list[OperationContract]:
    return [
        contract
        for contract in operation_contracts()
        if contract.role in {
            "prepare",
            "import",
            "export",
            "process",
            "post_import",
            "validate",
        }
    ]

