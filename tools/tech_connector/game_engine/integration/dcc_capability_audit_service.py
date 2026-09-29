"""Evidence-based audit of executable TC and bridged DCC surfaces."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
import importlib.util
from pathlib import Path
from typing import Any

from tech_connector.game_engine.authoring.rigging_workspace_service import RIGGING_CAPABILITIES
from tech_connector.game_engine.integration.dcc_operation_service import dcc_operation_registry
from tech_connector.game_engine.integration.rigging_host_adapter_service import (
    BLENDER_CAPABILITY_STATUS,
    MAX_CAPABILITY_STATUS,
    MAYA_CAPABILITY_STATUS,
    MOTIONBUILDER_CAPABILITY_STATUS,
)
from tech_connector.game_engine.integration.tc_rigging_host_adapter import TCRiggingHostAdapter


DCC_AUDIT_SCHEMA = "tech_connector.dcc_capability_audit.v1"
AUDITED_HOSTS = (
    "tech_connector", "maya", "blender", "3dsmax", "motionbuilder",
    "houdini", "substance_painter", "unreal", "unity", "photoshop", "gimp",
)


@dataclass(frozen=True)
class DccDepartmentEvidence:
    department: str
    status: str
    declared_operations: tuple[str, ...] = ()
    executable_operations: tuple[str, ...] = ()
    missing_operations: tuple[str, ...] = ()
    note: str = ""
    out_of_scope_operations: tuple[str, ...] = ()
    delegated_operations: tuple[str, ...] = ()


@dataclass(frozen=True)
class DccHostAudit:
    host: str
    status: str
    departments: tuple[DccDepartmentEvidence, ...]
    declared_operation_count: int = 0
    executable_operation_count: int = 0
    limitations: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def audit_dcc_capabilities(hosts: tuple[str, ...] = AUDITED_HOSTS) -> dict[str, Any]:
    reports = [audit_dcc_host(host) for host in hosts]
    return {
        "schema": DCC_AUDIT_SCHEMA,
        "hosts": [report.to_dict() for report in reports],
        "summary": {
            "host_count": len(reports),
            "operational_hosts": sum(report.status in {"native", "translated", "partial"} for report in reports),
            "unsupported_hosts": [report.host for report in reports if report.status == "unsupported"],
            "declared_operations": sum(report.declared_operation_count for report in reports),
            "structurally_executable_operations": sum(report.executable_operation_count for report in reports),
            "host_profile_out_of_scope_operations": sum(
                len(department.out_of_scope_operations)
                for report in reports
                for department in report.departments
            ),
            "delegated_operations": sum(
                len(department.delegated_operations)
                for report in reports
                for department in report.departments
            ),
        },
    }


def audit_dcc_host(host: str) -> DccHostAudit:
    key = str(host or "").strip().lower()
    if key == "tech_connector":
        return _audit_tc_native()
    registry = dcc_operation_registry(key)
    departments = _operation_departments(registry, host=key)
    rigging = _bridged_rigging_evidence(key)
    if rigging is not None:
        departments["rigging"] = rigging
    evidence = tuple(departments[name] for name in sorted(departments))
    declared = sum(len(row.declared_operations) for row in evidence)
    executable = sum(len(row.executable_operations) for row in evidence)
    if not registry and rigging is None:
        return DccHostAudit(
            key, "unsupported", (), limitations=(
                "No authoritative operation registry or rigging host adapter is installed.",
            ),
        )
    full = bool(evidence) and all(row.status == "translated" for row in evidence)
    limitations = (
        "Registered bridge operations are structurally callable but require a live-host integration test for release qualification.",
    )
    return DccHostAudit(
        key, "translated" if full else "partial", evidence, declared, executable,
        limitations=limitations,
    )


def _audit_tc_native() -> DccHostAudit:
    adapter = TCRiggingHostAdapter()
    declared = tuple(sorted(RIGGING_CAPABILITIES))
    implemented = tuple(
        key for key in declared if callable(getattr(adapter, "_op_" + key.replace(".", "_"), None))
    )
    missing = tuple(sorted(set(declared) - set(implemented)))
    rigging = DccDepartmentEvidence(
        "rigging", "native" if not missing else "partial", declared, implemented, missing,
        "Verified against concrete TC-native adapter handlers; behavioral host tests remain separate.",
    )
    return DccHostAudit(
        "tech_connector", rigging.status, (rigging,), len(declared), len(implemented),
        limitations=(
            "This audit covers the shared rigging contract, not every aspirational modeling, simulation, or rendering feature.",
        ),
    )


def _bridged_rigging_evidence(host: str) -> DccDepartmentEvidence | None:
    statuses = {
        "blender": BLENDER_CAPABILITY_STATUS,
        "3dsmax": MAX_CAPABILITY_STATUS,
        "maya": MAYA_CAPABILITY_STATUS,
        "motionbuilder": MOTIONBUILDER_CAPABILITY_STATUS,
    }.get(host)
    if statuses is None:
        return None
    out_of_scope = tuple(sorted(key for key, status in statuses.items() if status == "unsupported"))
    declared = tuple(sorted(key for key, status in statuses.items() if status != "unsupported"))
    executable = tuple(sorted(key for key, status in statuses.items() if status == "translated"))
    missing = tuple(sorted(key for key in declared if statuses.get(key) != "translated"))
    module = {
        "blender": "blender_tools/Rigging/rigging_host_adapter.py",
        "3dsmax": "max_tools/Rigging/rigging_host_adapter.py",
        "maya": "maya_tools/Rigging/rigging_host_adapter.py",
        "motionbuilder": "motionbuilder_tools/Rigging/rigging_host_adapter.py",
    }[host]
    module_exists = (_workspace_root() / module).is_file()
    status = "translated" if module_exists and not missing else "partial"
    if not module_exists:
        executable = ()
        missing = declared
    return DccDepartmentEvidence(
        department="rigging",
        status=status,
        declared_operations=declared,
        executable_operations=executable,
        missing_operations=missing,
        note=(
            "Host-profile adapter is present; live host readback is still required."
            if module_exists else "The declared host adapter module is missing."
        ),
        out_of_scope_operations=out_of_scope,
    )


def _operation_departments(registry: dict[str, Any], *, host: str = "") -> dict[str, DccDepartmentEvidence]:
    grouped: dict[str, list[tuple[str, Any]]] = {}
    for key, operation in sorted(registry.items()):
        department = _department_for_operation(key)
        grouped.setdefault(department, []).append((key, operation))
    result: dict[str, DccDepartmentEvidence] = {}
    for department, rows in grouped.items():
        declared = tuple(key for key, _operation in rows)
        delegated = tuple(
            key for key, operation in rows
            if str(getattr(operation, "execution_mode", "host_native")) == "user_delegated"
        )
        executable = tuple(
            key for key, operation in rows
            if key not in delegated and _callable_contract_exists(
                str(getattr(operation, "function", "")), host=host,
            )
        )
        missing = tuple(key for key in declared if key not in delegated and key not in executable)
        status = "translated" if not delegated and not missing else "partial"
        notes = []
        if executable:
            notes.append("Concrete host callable contracts are present.")
        if missing:
            notes.append("Some registered callable modules are missing.")
        if delegated:
            notes.append("Some operations require an explicit host-UI handoff.")
        result[department] = DccDepartmentEvidence(
            department=department,
            status=status,
            declared_operations=declared,
            executable_operations=executable,
            missing_operations=missing,
            note=" ".join(notes),
            delegated_operations=delegated,
        )
    return result


def _callable_contract_exists(function: str, *, host: str = "") -> bool:
    path = str(function or "").strip()
    if not path or "." not in path:
        return False
    if path.startswith("ai_studio."):
        return host in {"maya", "blender"}
    if path.startswith(("photoshop.command.", "gimp.command.", "unity.command.")):
        return True
    module_name, attribute = path.rsplit(".", 1)
    source_path = _workspace_python_source(module_name)
    if source_path is not None:
        try:
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        except (OSError, SyntaxError, UnicodeError):
            return False
        return any(
            (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and node.name == attribute
            )
            or (
                isinstance(node, (ast.Assign, ast.AnnAssign))
                and attribute in _assigned_names(node)
            )
            or (
                isinstance(node, (ast.Import, ast.ImportFrom))
                and attribute in _imported_names(node)
            )
            for node in tree.body
        )
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, AttributeError, ValueError):
        return False


def _workspace_python_source(module_name: str) -> Path | None:
    base = _workspace_root().joinpath(*module_name.split("."))
    module_path = base.with_suffix(".py")
    if module_path.is_file():
        return module_path
    package_path = base / "__init__.py"
    return package_path if package_path.is_file() else None


def _assigned_names(node: ast.Assign | ast.AnnAssign) -> set[str]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return {
        target.id
        for target in targets
        if isinstance(target, ast.Name)
    }


def _imported_names(node: ast.Import | ast.ImportFrom) -> set[str]:
    return {
        alias.asname or alias.name.rsplit(".", 1)[-1]
        for alias in node.names
    }


def _department_for_operation(operation: str) -> str:
    prefix = operation.split(".", 1)[0]
    if prefix in {"modeling", "mesh", "geometry"}:
        return "modeling"
    if prefix in {"material", "materials", "texture", "textures", "shader"}:
        return "lookdev"
    if prefix in {"animation", "character", "retarget"}:
        return "animation"
    if prefix in {"rig", "rigging", "skin", "constraints", "definition"}:
        return "rigging"
    if prefix in {"render", "simulation", "fx"}:
        return "rendering_simulation"
    if prefix in {"io", "assets", "project"}:
        return "interchange"
    return "scene_automation"


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


__all__ = [
    "AUDITED_HOSTS", "DCC_AUDIT_SCHEMA", "DccDepartmentEvidence", "DccHostAudit",
    "audit_dcc_capabilities", "audit_dcc_host",
]
