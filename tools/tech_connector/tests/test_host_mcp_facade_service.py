from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tech_connector.bridges import host_mcp_server
from tech_connector.services.host_mcp_facade_service import (
    MCP_HOSTS,
    MUTATION_ENV,
    RAW_EXECUTION_ENV,
    HostMcpFacade,
    facade_contract,
)
from tech_connector.services.settings_service import managed_host_mcp_server_specs, resolve_mcp_python_command


class FakePythonBridge:
    info = SimpleNamespace(supports_direct_execute=True)
    SYS_PATHS = [r"C:\depot\tools"]

    def __init__(self) -> None:
        self.calls = []

    def find_ports(self):
        return [7001, 7002]

    def session_info(self, *, port):
        return {"ok": True, "port": port, "label": f"session-{port}"}

    def execute(self, code, timeout=10.0):
        self.calls.append(("execute", None, code, timeout))
        return True, '{"value": 42}'

    def execute_on_port(self, code, *, port, timeout=10.0):
        self.calls.append(("execute_on_port", port, code, timeout))
        return True, '{"value": 42}'


class FakeCommandBridge(FakePythonBridge):
    def execute_command(self, command, params, **kwargs):
        self.calls.append(("execute_command", command, params, kwargs))
        return True, '{"command_ok": true}'


def test_every_declared_mcp_host_has_a_typed_operation_contract():
    contracts = [facade_contract(host) for host in MCP_HOSTS]

    assert all(contract["supported"] for contract in contracts)
    assert all(contract["operation_count"] > 0 for contract in contracts)
    assert all("execute_python" in contract["controlled_tools"] for contract in contracts)


def test_sessions_can_be_inspected_and_explicitly_selected():
    facade = HostMcpFacade("maya", bridge=FakePythonBridge(), environment={})

    assert facade.status()["ports"] == [7001, 7002]
    assert facade.select_session(9999)["ok"] is False
    assert facade.select_session(7002) == {"ok": True, "host": "maya", "selected_port": 7002}
    sessions = facade.sessions()
    assert [row["selected"] for row in sessions["sessions"]] == [False, True]


def test_read_operation_runs_without_mutation_opt_in_on_selected_session():
    bridge = FakePythonBridge()
    facade = HostMcpFacade("maya", bridge=bridge, environment={})
    facade.select_session(7002)

    receipt = facade.run_operation("scene.ls")

    assert receipt["ok"] is True
    assert receipt["session_port"] == 7002
    assert receipt["result"] == {"value": 42}
    assert bridge.calls[0][0:2] == ("execute_on_port", 7002)
    assert "maya.cmds" in bridge.calls[0][2]


@pytest.mark.parametrize(
    ("environment", "approved"),
    [({}, False), ({MUTATION_ENV: "1"}, False), ({}, True)],
)
def test_mutation_requires_both_installation_policy_and_per_call_approval(environment, approved):
    bridge = FakePythonBridge()
    facade = HostMcpFacade("maya", bridge=bridge, environment=environment)

    receipt = facade.run_operation("scene.select", {"objects": ["pCube1"]}, approved=approved)

    assert receipt["status"] == "approval_required"
    assert bridge.calls == []


def test_approved_mutation_runs_when_installation_policy_allows_it():
    bridge = FakePythonBridge()
    facade = HostMcpFacade("maya", bridge=bridge, environment={MUTATION_ENV: "true"})

    receipt = facade.run_operation("scene.select", {"objects": ["pCube1"]}, approved=True)

    assert receipt["ok"] is True
    assert receipt["mutates_project"] is True
    assert bridge.calls


def test_raw_execution_has_a_separate_stronger_policy_gate():
    bridge = FakePythonBridge()
    facade = HostMcpFacade("maya", bridge=bridge, environment={MUTATION_ENV: "1"})
    assert facade.execute_python("print('x')", approved=True)["status"] == "approval_required"

    facade = HostMcpFacade(
        "maya",
        bridge=bridge,
        environment={MUTATION_ENV: "1", RAW_EXECUTION_ENV: "1"},
    )
    assert facade.execute_python("print('x')", approved=True)["ok"] is True


def test_registered_script_operations_also_require_raw_execution_policy():
    bridge = FakePythonBridge()
    facade = HostMcpFacade("maya", bridge=bridge, environment={MUTATION_ENV: "1"})

    receipt = facade.run_operation("script.run", {"code": "print('x')"}, approved=True)

    assert receipt["status"] == "approval_required"
    assert receipt["requires_raw_execution"] is True
    assert bridge.calls == []


def test_raw_execution_stays_pinned_to_the_selected_session():
    bridge = FakePythonBridge()
    facade = HostMcpFacade(
        "maya",
        bridge=bridge,
        environment={MUTATION_ENV: "1", RAW_EXECUTION_ENV: "1"},
    )
    facade.select_session(7002)

    receipt = facade.execute_python("print('x')", approved=True)

    assert receipt["ok"] is True
    assert bridge.calls[0][0:2] == ("execute_on_port", 7002)


def test_command_bridges_use_their_native_command_protocol():
    bridge = FakeCommandBridge()
    facade = HostMcpFacade("gimp", bridge=bridge, environment={MUTATION_ENV: "1"})

    receipt = facade.run_operation(
        "image.convert_batch",
        {"files": ["a.png"], "target_format": "tga"},
        approved=True,
    )

    assert receipt["ok"] is True
    assert bridge.calls[0][0:2] == ("execute_command", "convert_image_format_batch")


def test_generated_server_specs_are_repo_owned_and_cover_all_shared_hosts():
    specs = managed_host_mcp_server_specs()
    assert set(specs) == set(MCP_HOSTS) - {"unreal"}
    for host, spec in specs.items():
        assert spec["args"][-2:] == ["--host", host]
        assert "host_mcp_server.py" in spec["args"][0]
        assert "Desktop\\UnrealGenAISupport" not in spec["args"][0]


def test_mcp_python_resolver_selects_an_interpreter_with_fastmcp():
    command = resolve_mcp_python_command()

    assert Path(command).is_file()
    assert all(spec["command"] == command for spec in managed_host_mcp_server_specs().values())


def test_checked_in_registry_and_config_match_managed_mcp_hosts():
    root = Path(__file__).resolve().parents[1]
    registry = json.loads((root / "plugins" / "plugin_registry.json").read_text(encoding="utf-8"))
    config = json.loads(
        (root / "knowledge" / "mcp_unreal_maya_knowledge_config.json").read_text(encoding="utf-8")
    )

    assert set(MCP_HOSTS) <= set(registry["plugins"])
    assert all(registry["plugins"][host]["supports_mcp"] for host in MCP_HOSTS)
    assert registry["plugins"]["unreal"]["default_port"] == 12347
    assert set(MCP_HOSTS) <= set(config["mcpServers"])


def test_generic_server_registers_namespaced_tools(monkeypatch):
    class FakeFacade:
        host = "maya"

        def __init__(self, host):
            assert host == "maya"

    class FakeFastMcp:
        def __init__(self, name):
            self.name = name
            self.tools = {}

        def tool(self):
            def decorate(function):
                self.tools[function.__name__] = function
                return function

            return decorate

    monkeypatch.setattr(host_mcp_server, "HostMcpFacade", FakeFacade)
    server = host_mcp_server.create_host_mcp_server("maya", fastmcp_class=FakeFastMcp)

    assert set(server.tools) == {
        "maya_status",
        "maya_sessions",
        "maya_select_session",
        "maya_operation_catalog",
        "maya_validate_operation",
        "maya_run_operation",
        "maya_execute_python",
    }
