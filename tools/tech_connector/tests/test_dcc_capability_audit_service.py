from tech_connector.game_engine.authoring.rigging_workspace_service import RIGGING_CAPABILITIES
from tech_connector.game_engine.integration.dcc_capability_audit_service import (
    AUDITED_HOSTS,
    _callable_contract_exists,
    audit_dcc_capabilities,
    audit_dcc_host,
)
from tech_connector.game_engine.integration.rigging_host_adapter_service import (
    MOTIONBUILDER_CAPABILITY_STATUS,
)
from tech_connector.services.unreal.unreal_operation_service import UNREAL_OPERATIONS


def test_tc_rigging_audit_checks_concrete_handlers() -> None:
    report = audit_dcc_host("tech_connector")
    assert report.status == "native"
    assert report.executable_operation_count == len(RIGGING_CAPABILITIES)
    assert not report.departments[0].missing_operations


def test_3dsmax_audit_requires_a_concrete_operation_registry() -> None:
    report = audit_dcc_host("3dsmax")
    assert report.status == "translated"
    assert report.executable_operation_count >= 12
    assert report.executable_operation_count == report.declared_operation_count


def test_maya_and_motionbuilder_are_audited_against_their_host_profiles() -> None:
    maya = audit_dcc_host("maya")
    mobu = audit_dcc_host("motionbuilder")
    maya_rigging = next(row for row in maya.departments if row.department == "rigging")
    mobu_rigging = next(row for row in mobu.departments if row.department == "rigging")
    assert maya_rigging.status == "translated"
    assert not maya_rigging.missing_operations
    assert mobu.status == "translated"
    assert mobu_rigging.status == "translated"
    assert not mobu_rigging.missing_operations
    assert "rig.create_ribbon" in mobu_rigging.out_of_scope_operations
    assert set(mobu_rigging.out_of_scope_operations) == {
        key for key, status in MOTIONBUILDER_CAPABILITY_STATUS.items() if status == "unsupported"
    }


def test_delegated_host_ui_operations_are_not_counted_as_executable() -> None:
    report = audit_dcc_host("substance_painter")
    lookdev = next(row for row in report.departments if row.department == "lookdev")

    assert report.status == "partial"
    assert lookdev.delegated_operations == ("material.apply",)
    assert "material.apply" not in lookdev.executable_operations
    assert "material.apply" not in lookdev.missing_operations

    unreal = audit_dcc_host("unreal")
    unreal_blueprints = next(row for row in unreal.departments if row.department == "scene_automation")
    assert "blueprint.open_graph" in unreal_blueprints.delegated_operations
    assert "blueprint.create_variable" in unreal_blueprints.executable_operations
    assert "blueprint.add_component" in unreal_blueprints.executable_operations
    assert "blueprint.create_variable" not in unreal_blueprints.missing_operations
    for operation in unreal_blueprints.delegated_operations:
        handoff = UNREAL_OPERATIONS[operation].delegation
        assert handoff["surface"]
        assert handoff["action"]
        assert handoff["verification"]


def test_workspace_callable_audit_checks_the_named_attribute_without_importing_host_sdks() -> None:
    assert _callable_contract_exists(
        "motionbuilder_tools.character.plot_animation",
        host="motionbuilder",
    )
    assert not _callable_contract_exists(
        "motionbuilder_tools.character.missing_plot_animation",
        host="motionbuilder",
    )


def test_full_audit_exposes_honest_summary() -> None:
    audit = audit_dcc_capabilities()
    assert audit["schema"].endswith(".v1")
    assert not audit["summary"]["unsupported_hosts"]
    assert audit["summary"]["operational_hosts"] == audit["summary"]["host_count"]
    assert len([host for host in AUDITED_HOSTS if host != "tech_connector"]) == 10
    assert audit["summary"]["structurally_executable_operations"] > 0
