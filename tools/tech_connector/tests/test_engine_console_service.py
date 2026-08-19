from __future__ import annotations

from tech_connector.services.engine_console_service import EngineConsoleSession, parse_tc_command


def test_python_console_captures_output_last_expression_errors_and_persistent_state() -> None:
    session = EngineConsoleSession()
    first = session.execute_python("value = engine_value * 2\nprint('ready')\nvalue", {"engine_value": 4})
    second = session.execute_python("value + 1")
    failed = session.execute_python("raise RuntimeError('broken')")

    assert first.ok and first.output == "ready\n" and first.result_repr == "8"
    assert second.result_repr == "9"
    assert not failed.ok and "RuntimeError: broken" in failed.error
    assert len(session.history) == 3


def test_tc_command_console_parses_json_or_command_plus_payload_and_captures_receipt() -> None:
    calls = []

    def execute(command: str, **payload):
        calls.append((command, payload))
        return {"executed": True, "command": command, "payload": payload}

    session = EngineConsoleSession()
    first = session.execute_tc_command('{"command":"world_ai.find_path","payload":{"start":"a","goal":"b"}}', execute)
    second = session.execute_tc_command("gameplay.runtime_budget\n{\"target\": \"web\"}", execute)

    assert first.ok and '"executed": true' in first.output
    assert second.ok and calls[-1] == ("gameplay.runtime_budget", {"target": "web"})
    assert parse_tc_command("characters.choose_action") == ("characters.choose_action", {})
