from __future__ import annotations

from tech_connector.services.application_command_service import ApplicationCommandService


def test_application_command_exposes_open_knowledge_credits(monkeypatch) -> None:
    monkeypatch.setattr(
        "tech_connector.services.knowledge_credits_service.list_knowledge_credits",
        lambda query="": [{"title": "Source", "query": query}],
    )

    result = ApplicationCommandService().execute(
        "list_knowledge_credits",
        {"query": "ledge"},
    )

    assert result["ok"]
    assert result["policy"] == "open_information_only"
    assert result["credits"] == [{"title": "Source", "query": "ledge"}]
