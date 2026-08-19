from __future__ import annotations

import json

from tech_connector.bridges.gimp.gimp_bridge import GimpBridge
from tech_connector.bridges.max.max_bridge import MaxBridge
from tech_connector.bridges.photoshop.photoshop_bridge import PhotoshopBridge
from tech_connector.game_engine.integration.dcc_operation_service import dcc_operation_registry
from tech_connector.game_engine.integration.pipeline_operation_runtime_service import execute_pipeline_operation


def test_generic_python_host_operation_stays_on_explicit_session(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        MaxBridge,
        "execute_on_port",
        lambda self, code, *, port, timeout: calls.append((code, port, timeout))
        or (True, json.dumps({"host": "3dsmax", "port": port})),
    )
    operation = dcc_operation_registry("3dsmax")["scene.list"]

    result = execute_pipeline_operation(
        "3dsmax", operation.key, operation.function, {}, session_port=7094,
    )

    assert result == {"host": "3dsmax", "port": 7094}
    assert calls[0][1] == 7094
    assert operation.function in calls[0][0]


def test_photoshop_and_gimp_operations_stay_on_explicit_sessions(monkeypatch) -> None:
    photoshop_calls = []
    gimp_calls = []
    monkeypatch.setattr(
        PhotoshopBridge,
        "execute_on_port",
        lambda self, code, *, port, timeout: photoshop_calls.append((json.loads(code), port, timeout))
        or (True, json.dumps({"host": "photoshop", "port": port})),
    )
    monkeypatch.setattr(
        GimpBridge,
        "execute_command",
        lambda self, command, params, *, port=None: gimp_calls.append((command, params, port))
        or (True, json.dumps({"host": "gimp", "port": port})),
    )

    photoshop = execute_pipeline_operation(
        "photoshop",
        "document.info",
        "photoshop.command.document.info",
        {},
        session_port=7064,
    )
    gimp = execute_pipeline_operation(
        "gimp",
        "image.convert_batch",
        "gimp.command.convert_image_format_batch",
        {"files": ["a.png"]},
        session_port=7084,
    )

    assert photoshop == {"host": "photoshop", "port": 7064}
    assert photoshop_calls[0][0]["command"] == "document.info"
    assert photoshop_calls[0][1] == 7064
    assert gimp == {"host": "gimp", "port": 7084}
    assert gimp_calls[0][2] == 7084
