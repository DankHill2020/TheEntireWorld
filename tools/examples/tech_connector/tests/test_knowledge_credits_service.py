from __future__ import annotations

from tech_connector.services.knowledge_credits_service import (
    list_knowledge_credits,
    register_open_knowledge_sources,
)


def _open_source() -> dict:
    return {
        "title": "Public Traversal Technique",
        "creator": "Example Creator",
        "url": "https://example.org/traversal",
        "public_access": True,
        "license": "CC BY 4.0",
    }


def test_registry_deduplicates_and_accumulates_learned_uses(tmp_path) -> None:
    path = tmp_path / "credits.json"
    first = register_open_knowledge_sources(
        [_open_source()],
        what_learned="ledge detection",
        domains=["unreal", "animation"],
        path=path,
    )
    second = register_open_knowledge_sources(
        [_open_source()],
        what_learned="corner transitions",
        domains=["traversal"],
        path=path,
    )

    assert len(first["added"]) == 1
    assert len(second["updated"]) == 1
    rows = list_knowledge_credits(path)
    assert len(rows) == 1
    assert rows[0]["learned_uses"] == ["ledge detection", "corner transitions"]
    assert set(rows[0]["domains"]) == {"unreal", "animation", "traversal"}


def test_registry_refuses_restricted_sources_without_creating_file(tmp_path) -> None:
    path = tmp_path / "credits.json"
    result = register_open_knowledge_sources(
        [
            {
                "title": "Paid Course",
                "url": "https://example.org/course",
                "public_access": True,
                "paid": True,
                "license": "Commercial",
            }
        ],
        path=path,
    )

    assert len(result["rejected"]) == 1
    assert result["total"] == 0
    assert not path.exists()


def test_registry_searches_creator_and_knowledge_use(tmp_path) -> None:
    path = tmp_path / "credits.json"
    register_open_knowledge_sources([_open_source()], what_learned="prone crawl", path=path)

    assert len(list_knowledge_credits(path, query="example creator")) == 1
    assert len(list_knowledge_credits(path, query="prone")) == 1
    assert list_knowledge_credits(path, query="grapple") == []
