from __future__ import annotations

from pathlib import Path

import pytest

from tech_connector.api import APIResult, TechConnectorAPIError, TechConnectorHeadlessAPI


class _Entitlement:
    def to_dict(self):
        return {"tier": "test", "capabilities": ["official_api_access"]}


def _api(project_root: Path | None = None) -> TechConnectorHeadlessAPI:
    api = TechConnectorHeadlessAPI(
        settings={}, project_root=project_root, require_entitlement=False,
        licensing_context=object(),
    )
    api._require_unlocked = lambda: _Entitlement()
    api._tag = lambda *_args, **_kwargs: {"operation": _kwargs.get("operation", "")}
    return api


def test_api_result_has_structured_errors_and_simple_unwrap() -> None:
    success = APIResult(True, result={"value": 7})
    assert success and success.unwrap() == {"value": 7}

    failure = APIResult(False, error="Unknown API feature: missing")
    assert not failure
    assert failure.error_detail["code"] == "not_found"
    assert failure.to_dict()["error_detail"]["suggestion"]
    with pytest.raises(TechConnectorAPIError) as raised:
        failure.unwrap()
    assert raised.value.code == "not_found"
    assert not raised.value.retryable


def test_api_discovery_search_and_operation_help_are_self_describing() -> None:
    api = _api()
    overview = api.describe()
    assert overview["api_version"] == "2.0"
    assert overview["aliases"]["game_engine"] == "kingdom"
    assert overview["result_contract"]["raise_on_error"] == "result.unwrap()"

    matches = api.features.search("model generation")
    assert any(item["feature_id"] == "ai.generate" for item in matches)
    help_payload = api.features.describe("ai.generate", "route")
    operation = help_payload["operations"][0]
    assert operation["name"] == "route"
    assert operation["callable"]
    assert {item["name"] for item in operation["parameters"]} >= {"model", "depth"}


def test_kingdom_editor_api_exposes_dependency_operations(tmp_path: Path) -> None:
    api = _api(tmp_path)
    editor = api.kingdom._editor_api()
    source = tmp_path / "Assets" / "Level.tcscene"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"level")
    record = editor.database.register_asset(source, "tc.level")

    described = api.kingdom.editor_describe("asset_dependency_graph")
    assert described.ok, described.error
    assert described.result["value"]["operations"][0]["name"] == "asset_dependency_graph"

    result = api.kingdom.editor_call("asset_dependency_graph", asset_id=record.asset_id)
    assert result.ok, result.error
    assert result.result["value"]["root_asset_id"] == record.asset_id
    assert result.result["value"]["package_bytes"] == len(b"level")

    unknown = api.kingdom.editor_call("not_an_operation")
    assert not unknown
    assert unknown.error_detail["code"] == "not_found"
