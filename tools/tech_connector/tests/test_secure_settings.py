"""Tests for separating credentials from ordinary settings JSON."""

from __future__ import annotations

import json
import os

import pytest

from tech_connector.services import settings_service
from tech_connector.services.credential_store import WindowsDpapiCredentialStore


class MemoryCredentialStore:
    def __init__(self) -> None:
        self.values = {}

    def load(self, key: str) -> str:
        return self.values.get(key, "")

    def save(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


def test_save_settings_keeps_secrets_out_of_json(tmp_path, monkeypatch) -> None:
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings_service, "APP_DIR", tmp_path)
    monkeypatch.setattr(settings_service, "SETTINGS_PATH", path)
    store = MemoryCredentialStore()

    settings_service.save_settings(
        {"theme": "dark", "openai_api_key": "top-secret"},
        credential_store=store,
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {"theme": "dark"}
    assert store.values["openai_api_key"] == "top-secret"


def test_load_settings_migrates_plaintext_secrets(tmp_path, monkeypatch) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"theme": "dark", "github_token": "legacy-secret"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings_service, "APP_DIR", tmp_path)
    monkeypatch.setattr(settings_service, "SETTINGS_PATH", path)
    store = MemoryCredentialStore()

    loaded = settings_service.load_settings(credential_store=store)

    assert loaded["github_token"] == "legacy-secret"
    assert "github_token" not in json.loads(path.read_text(encoding="utf-8"))
    assert store.values["github_token"] == "legacy-secret"


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI test")
def test_windows_dpapi_store_round_trip(tmp_path) -> None:
    store = WindowsDpapiCredentialStore(tmp_path)

    store.save("provider_token", "protected-value")

    assert store.load("provider_token") == "protected-value"
    credential_file = next((tmp_path / "credentials").iterdir())
    assert b"protected-value" not in credential_file.read_bytes()
    store.delete("provider_token")
    assert store.load("provider_token") == ""
