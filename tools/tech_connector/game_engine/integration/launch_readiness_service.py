from __future__ import annotations

"""Unified, fail-closed launch audit across product, API, assets, and DCC evidence."""

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from tech_connector.game_engine.assets.asset_type_registry import builtin_asset_type_registry
from tech_connector.game_engine.integration.adaptive_scene_command_service import ADAPTIVE_SCENE_COMMANDS
from tech_connector.game_engine.integration.capability_maturity_service import audit_capability_maturity
from tech_connector.game_engine.integration.dcc_release_readiness_service import audit_dcc_release_readiness
from tech_connector.game_engine.integration.playable_project_qualification_service import (
    load_playable_project_qualification, validate_playable_project_qualification,
)
from tech_connector.game_engine.integration.fx_qualification_service import (
    load_realtime_fx_qualification, validate_realtime_fx_qualification,
)
from tech_connector.game_engine.integration.world_production_qualification_service import (
    load_world_production_qualification, validate_world_production_qualification,
)
from tech_connector.game_engine.integration.content_production_qualification_service import (
    load_content_production_qualification, validate_content_production_qualification,
)
from tech_connector.game_engine.integration.capability_qualification_service import (
    load_capability_qualification, validate_capability_qualification,
)
from tech_connector.game_engine.integration.release_regression_qualification_service import (
    load_release_regression_qualification, validate_release_regression_qualification,
)
from tech_connector.packaging.release_gate import (
    publication_candidates, sensitive_artifacts, validate_github_root_surface, validate_legal_surface,
    validate_production_configuration, validate_production_legal_approval, validate_production_source_access,
)


LAUNCH_READINESS_SCHEMA = "tech_connector.launch_readiness.v1"

LAUNCH_GATE_REMEDIATION: dict[str, tuple[str, ...]] = {
    "public_package": ("Remove or relocate every reported private/sensitive artifact, then run the audit again.",),
    "python_api_parity": ("Implement every reported Editor API operation and expose it through TCEditorAPI.",),
    "playable_project_qualification": ("Run the playable-project qualification against the current source revision and native player.",),
    "realtime_fx_qualification": ("Run the realtime FX qualification and resolve every solver, budget, visual-readback, or GPU-backend fallback failure.",),
    "world_production_qualification": ("Run the world-production qualification for terrain, foliage, navigation, partitioning, and procedural assets.",),
    "content_production_qualification": ("Run the content-production qualification for every registered authoring asset type.",),
    "asset_ux_contracts": ("Give every reported asset type a dedicated editor and a callable Python API namespace.",),
    "asset_production_readiness": ("Qualify each reported asset in a production vertical slice or promote it only after executable evidence passes.",),
    "capability_evidence_qualification": ("Regenerate capability evidence on this exact source revision and fix every failing evidence test.",),
    "release_regression_qualification": ("Run the complete release regression qualification with the supported Python runtime and resolve every failure.",),
    "capability_maturity": ("Replace contract/reference implementations with tested production behavior for every reported command.",),
    "dcc_qualification": (
        "Open each required DCC, activate its authenticated Tech Connector bridge, and select the exact live session.",
        "For that same session, run Host Qualification, Source Parity, and the host's Production Workflow; keep exported artifacts unchanged until the audit completes.",
    ),
    "production_controls": (
        "Configure the real licensing endpoints and entitlement public key; test activation, refresh, registration, entitlement, and deactivation.",
        "Record counsel approval, verify the account-gated distribution, and attach the protected-source access review reference and timestamp.",
    ),
}


@dataclass(frozen=True)
class LaunchGate:
    gate: str
    status: str
    blockers: tuple[str, ...] = ()
    evidence: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["remediation"] = list(LAUNCH_GATE_REMEDIATION.get(self.gate, ())) if self.status != "passed" else []
        return row


def audit_launch_readiness(
    source_root: str | Path, *, editor_api: Any | None = None,
    qualification_receipts: Mapping[str, Any] | None = None,
    workflow_receipts: Mapping[str, Any] | None = None,
    source_parity_receipts: Mapping[str, Any] | None = None,
    production: bool = False,
) -> dict[str, Any]:
    root = Path(source_root).expanduser().resolve(); gates: list[LaunchGate] = []
    public_failures = [*validate_legal_surface(root), *validate_github_root_surface(root),
                       *sensitive_artifacts(publication_candidates(root))]
    gates.append(LaunchGate("public_package", "passed" if not public_failures else "blocked", tuple(public_failures)))

    api_missing: list[str] = []
    contract: dict[str, Any] = {}
    if editor_api is not None:
        contract = dict(editor_api.capability_contract())
        for section, operations in contract.items():
            if not section.endswith("_operations") or not isinstance(operations, list): continue
            api_missing.extend(f"{section}.{operation}" for operation in operations if not callable(getattr(editor_api, str(operation), None)))
    else:
        api_missing.append("editor_api was not supplied")
    gates.append(LaunchGate("python_api_parity", "passed" if not api_missing else "blocked", tuple(api_missing),
                            {"operation_count": sum(len(value) for key, value in contract.items() if key.endswith("_operations") and isinstance(value, list))}))

    project_root = Path(getattr(editor_api, "project_root", root))
    playable_receipt_path = project_root / ".tech_connector" / "qualification" / "playable_project" / "playable_project_qualification.json"
    playable_receipt = load_playable_project_qualification(playable_receipt_path)
    playable_validation = validate_playable_project_qualification(root, playable_receipt)
    playable_blockers = [f"playable_project.{gate}" for gate in playable_validation["gates"]]
    gates.append(LaunchGate(
        "playable_project_qualification", "passed" if not playable_blockers else "blocked",
        tuple(playable_blockers),
        {"receipt": str(playable_receipt_path), "validation": playable_validation,
         "variants": list(playable_receipt.get("variants") or ())},
    ))
    fx_receipt_path = project_root / ".tech_connector" / "qualification" / "realtime_fx" / "realtime_fx_qualification.json"
    fx_receipt = load_realtime_fx_qualification(fx_receipt_path)
    fx_validation = validate_realtime_fx_qualification(root, fx_receipt, require_production_backend=True)
    fx_blockers = [f"realtime_fx.{gate}" for gate in fx_validation["gates"]]
    gates.append(LaunchGate(
        "realtime_fx_qualification", "passed" if not fx_blockers else "blocked", tuple(fx_blockers),
        {"receipt": str(fx_receipt_path), "validation": fx_validation,
         "covered_solver_profiles": list(fx_receipt.get("covered_solver_profiles") or ()),
         "unqualified_solver_profiles": list(fx_receipt.get("unqualified_solver_profiles") or ()),
         "gpu_qualification": dict(fx_receipt.get("gpu_qualification") or {}),
         "production_backend_qualification": dict(fx_receipt.get("production_backend_qualification") or {})},
    ))
    world_receipt_path = project_root / ".tech_connector" / "qualification" / "world_production" / "world_production_qualification.json"
    world_receipt = load_world_production_qualification(world_receipt_path)
    world_validation = validate_world_production_qualification(root, world_receipt)
    world_blockers = [f"world_production.{gate}" for gate in world_validation["gates"]]
    gates.append(LaunchGate(
        "world_production_qualification", "passed" if not world_blockers else "blocked", tuple(world_blockers),
        {"receipt": str(world_receipt_path), "validation": world_validation,
         "elapsed_seconds": world_receipt.get("elapsed_seconds"),
         "qualified_asset_types": list(world_receipt.get("qualified_asset_types") or ())},
    ))
    content_receipt_path = project_root / ".tech_connector" / "qualification" / "content_production" / "content_production_qualification.json"
    content_receipt = load_content_production_qualification(content_receipt_path)
    content_validation = validate_content_production_qualification(root, content_receipt)
    content_blockers = [f"content_production.{gate}" for gate in content_validation["gates"]]
    gates.append(LaunchGate(
        "content_production_qualification", "passed" if not content_blockers else "blocked", tuple(content_blockers),
        {"receipt": str(content_receipt_path), "validation": content_validation,
         "elapsed_seconds": content_receipt.get("elapsed_seconds"),
         "qualified_asset_types": list(content_receipt.get("qualified_asset_types") or ())},
    ))

    registry = builtin_asset_type_registry(); creatable = registry.all(creatable=True)
    asset_blockers = [f"{item.type_id}: missing dedicated editor" for item in creatable if item.editor_id == "generic"]
    asset_blockers.extend(f"{item.type_id}: missing Python namespace" for item in creatable if not item.python_api_namespace)
    gates.append(LaunchGate("asset_ux_contracts", "passed" if not asset_blockers else "blocked", tuple(asset_blockers),
                            {"creatable_asset_types": len(creatable), "production_ready": sum(item.maturity == "production_ready" for item in creatable),
                             "runtime_ready": sum(item.maturity in {"runtime_ready", "production_ready"} for item in creatable)}))
    maturity_counts = {
        maturity: sum(item.maturity == maturity for item in creatable)
        for maturity in sorted({item.maturity for item in creatable})
    }
    playable_asset_types = set(playable_receipt.get("qualified_asset_types") or ()) if playable_validation["valid"] else set()
    fx_asset_types = set(fx_receipt.get("qualified_asset_types") or ()) if fx_validation["valid"] else set()
    world_asset_types = set(world_receipt.get("qualified_asset_types") or ()) if world_validation["valid"] else set()
    content_asset_types = set(content_receipt.get("qualified_asset_types") or ()) if content_validation["valid"] else set()
    evidence_asset_types = playable_asset_types | fx_asset_types | world_asset_types | content_asset_types
    asset_qualification_blockers = [
        f"{item.type_id}: {item.maturity} (no current production qualification)"
        for item in creatable
        if item.maturity != "production_ready" and item.type_id not in evidence_asset_types
    ]
    gates.append(LaunchGate(
        "asset_production_readiness",
        "passed" if not asset_qualification_blockers else "blocked",
        tuple(asset_qualification_blockers),
        {"counts": maturity_counts, "required_maturity": "production_ready or fresh executable qualification",
         "evidence_qualified_in_vertical_slices": sorted(evidence_asset_types),
         "evidence_qualified_count": len(evidence_asset_types),
         "unqualified_asset_types": [item.type_id for item in creatable if item.maturity != "production_ready" and item.type_id not in evidence_asset_types]},
    ))

    capability_receipt_path = project_root / ".tech_connector" / "qualification" / "capabilities" / "capability_qualification.json"
    capability_receipt = load_capability_qualification(capability_receipt_path)
    capability_validation = validate_capability_qualification(root, capability_receipt)
    capability_evidence_blockers = [f"capability_evidence.{gate}" for gate in capability_validation["gates"]]
    gates.append(LaunchGate(
        "capability_evidence_qualification", "passed" if not capability_evidence_blockers else "blocked",
        tuple(capability_evidence_blockers),
        {"receipt": str(capability_receipt_path), "validation": capability_validation,
         "passed_tests": capability_receipt.get("passed_tests"),
         "production_capability_count": len(capability_receipt.get("production_capabilities") or ())},
    ))

    regression_receipt_path = project_root / ".tech_connector" / "qualification" / "release_regression" / "release_regression_qualification.json"
    regression_receipt = load_release_regression_qualification(regression_receipt_path)
    regression_validation = validate_release_regression_qualification(root, regression_receipt)
    regression_blockers = [f"release_regression.{gate}" for gate in regression_validation["gates"]]
    gates.append(LaunchGate(
        "release_regression_qualification", "passed" if not regression_blockers else "blocked",
        tuple(regression_blockers),
        {"receipt": str(regression_receipt_path), "validation": regression_validation,
         "passed_tests": regression_receipt.get("passed_tests"),
         "skipped_tests": regression_receipt.get("skipped_tests"),
         "interpreter": dict(regression_receipt.get("interpreter") or {})},
    ))
    capabilities = audit_capability_maturity(ADAPTIVE_SCENE_COMMANDS.values())
    capability_blockers = [f"{row['capability']}: {row['verified_maturity']}" for row in capabilities["capabilities"]
                           if row["verified_maturity"] not in {"production", "qualified"}]
    gates.append(LaunchGate("capability_maturity", "passed" if not capability_blockers else "blocked",
                            tuple(capability_blockers), {"counts": capabilities["counts"]}))

    dcc = audit_dcc_release_readiness(
        qualification_receipts=(None if qualification_receipts is None else dict(qualification_receipts)),
        workflow_receipts=(None if workflow_receipts is None else dict(workflow_receipts)),
        source_parity_receipts=(None if source_parity_receipts is None else dict(source_parity_receipts)),
    )
    dcc_blockers = [f"{row['host']}: " + ", ".join(row["structural_gates"] + row["evidence_gates"])
                    for row in dcc["hosts"] if row["status"] != "release_qualified"]
    dcc_evidence = dict(dcc["summary"])
    dcc_evidence["hosts"] = list(dcc["hosts"])
    gates.append(LaunchGate("dcc_qualification", "passed" if not dcc_blockers else "blocked", tuple(dcc_blockers), dcc_evidence))

    if production:
        production_failures = [*validate_production_configuration(root), *validate_production_legal_approval(root),
                               *validate_production_source_access(root)]
        gates.append(LaunchGate("production_controls", "passed" if not production_failures else "blocked", tuple(production_failures)))
    blocking = [gate.gate for gate in gates if gate.status != "passed"]
    return {"schema": LAUNCH_READINESS_SCHEMA, "status": "launch_ready" if not blocking else "blocked",
            "production": bool(production), "blocking_gates": blocking, "gates": [gate.to_dict() for gate in gates]}


__all__ = ["LAUNCH_GATE_REMEDIATION", "LAUNCH_READINESS_SCHEMA", "LaunchGate", "audit_launch_readiness"]
