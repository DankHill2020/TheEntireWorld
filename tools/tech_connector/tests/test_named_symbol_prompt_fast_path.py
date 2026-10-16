from reasoning_runtime import SymbolHit
from reasoning_runtime.engine.request_context import RequestContext
from tech_connector.engine.request_engine import RequestEngine


def _hit(path, *, symbol_id=1, name="build_asset"):
    return SymbolHit(
        symbol_id=symbol_id,
        name=name,
        qualname=name,
        kind="function",
        path=str(path),
        start_line=1,
    )


def test_exact_named_function_is_verified_and_follow_up_uses_same_source(tmp_path, monkeypatch):
    path = tmp_path / "sample_tool.py"
    path.write_text('def build_asset(value):\n    """Build an asset from a value."""\n    return value\n', encoding="utf-8")
    monkeypatch.setattr(
        "tech_connector.services.symbol_lookup_service.find_symbols",
        lambda *_args, **_kwargs: [_hit(path)],
    )
    engine = RequestEngine.__new__(RequestEngine)
    first = engine._fast_named_symbol_lookup(RequestContext(
        "Find function build_asset()", project_roots=(str(tmp_path),),
    ))

    assert first.action == "answer"
    assert first.metadata["selected_file"] == str(path)
    assert first.metadata["selected_callable"] == "build_asset"
    assert f"{path}:1" in first.text

    second = engine._fast_contextual_symbol_inspection(RequestContext(
        "Explain that function", project_roots=(str(tmp_path),),
        extras={"operation_memory": {
            "selected_file": first.metadata["selected_file"],
            "selected_callable": first.metadata["selected_callable"],
        }},
    ))
    assert second.action == "answer"
    assert "Build an asset from a value" in second.text


def test_named_symbol_does_not_trust_stale_index_entry(tmp_path, monkeypatch):
    path = tmp_path / "sample_tool.py"
    path.write_text("def other_function():\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(
        "tech_connector.services.symbol_lookup_service.find_symbols",
        lambda *_args, **_kwargs: [_hit(path)],
    )
    engine = RequestEngine.__new__(RequestEngine)
    result = engine._fast_named_symbol_lookup(RequestContext(
        "Find function build_asset()", project_roots=(str(tmp_path),),
    ))
    assert result.action == "clarify"
    assert result.metadata["result_type"] == "named_symbol_stale"


def test_named_symbol_asks_when_multiple_definitions_match(tmp_path, monkeypatch):
    first_path = tmp_path / "first.py"
    second_path = tmp_path / "second.py"
    for path in (first_path, second_path):
        path.write_text("def build_asset():\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(
        "tech_connector.services.symbol_lookup_service.find_symbols",
        lambda *_args, **_kwargs: [_hit(first_path), _hit(second_path, symbol_id=2)],
    )
    engine = RequestEngine.__new__(RequestEngine)
    result = engine._fast_named_symbol_lookup(RequestContext(
        "Find function build_asset()", project_roots=(str(tmp_path),),
    ))
    assert result.action == "clarify"
    assert str(first_path) in result.text
    assert str(second_path) in result.text
