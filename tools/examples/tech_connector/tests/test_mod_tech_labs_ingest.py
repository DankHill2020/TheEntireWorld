"""Tests for MOD Tech Labs swappable ingestion provider."""

import io
import json
import urllib.request
import zipfile
from pathlib import Path
import pytest

from tech_connector.services.settings_service import load_settings, save_settings, SETTINGS_PATH
from tech_connector.services.github_ingest_service import download_and_extract_repo


@pytest.fixture
def temp_settings():
    """Backup settings before test, restore after."""
    backup = None
    if SETTINGS_PATH.exists():
        try:
            backup = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    yield
    if backup is not None:
        try:
            SETTINGS_PATH.write_text(json.dumps(backup, indent=2), encoding="utf-8")
        except Exception:
            pass


class MockOpener:
    """Mock URL Opener to intercept API requests."""
    def __init__(self):
        self.requests = []
        self.mock_zip_bytes = b""

    def open(self, request, timeout=None):
        if isinstance(request, str):
            request = urllib.request.Request(request)

        url = request.get_full_url()
        method = request.get_method()
        self.requests.append((method, url))

        # Check endpoints
        if "run" in url and method == "POST":
            # Workflow Run trigger
            body = request.data.decode("utf-8")
            body_json = json.loads(body)
            assert "zip_url" in body_json["inputs"]
            
            response_data = {"run_id": "run_test_123", "status": "running"}
            return io.BytesIO(json.dumps(response_data).encode("utf-8"))

        elif "runs/run_test_123" in url and method == "GET":
            # Run Status Poller
            response_data = {
                "status": "completed",
                "outputs": {
                    "processed_zip": "https://mock.modtechlabs.com/outputs/processed_test.zip"
                }
            }
            return io.BytesIO(json.dumps(response_data).encode("utf-8"))

        elif "processed_test.zip" in url and method == "GET":
            # ZIP Download
            return io.BytesIO(self.mock_zip_bytes)

        raise ValueError(f"Unexpected mock request: {method} {url}")


def test_mod_tech_labs_ingest_pipeline(temp_settings, tmp_path, monkeypatch):
    """Test full MOD Tech Labs workflow ingestion process using mocked endpoints."""
    # 1. Setup mock credentials
    settings = load_settings()
    settings["github_ingest_provider_type"] = "mod_tech_labs"
    settings["mod_tech_labs_api_key"] = "test-api-key"
    settings["mod_tech_labs_workflow_id"] = "test-wf-uuid"
    save_settings(settings)

    # 2. Build mock zip data containing a test file
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as z:
        z.writestr("test_folder/processed_file.txt", "mod_tech_labs_optimized_asset")
    
    mock_opener = MockOpener()
    mock_opener.mock_zip_bytes = zip_buffer.getvalue()

    # 3. Patch urllib.request.build_opener to return our MockOpener
    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: mock_opener)

    # 4. Trigger download
    target_parent = tmp_path / "repos"
    target_parent.mkdir()
    
    result_path = download_and_extract_repo(
        repo_name="my_test_repo",
        repo_url="https://github.com/my_user/my_test_repo",
        target_parent_dir=target_parent
    )

    # 5. Assertions
    # Verify resulting path exists and matches expected folder structure
    assert result_path.exists()
    assert result_path.name == "my_test_repo"
    
    extracted_file = result_path / "processed_file.txt"
    assert extracted_file.exists()
    assert extracted_file.read_text() == "mod_tech_labs_optimized_asset"

    # Verify requests were made in the correct sequence
    assert len(mock_opener.requests) == 3
    assert mock_opener.requests[0] == ("POST", "https://api.modtechlabs.com/v1/workflows/test-wf-uuid/run")
    assert mock_opener.requests[1] == ("GET", "https://api.modtechlabs.com/v1/runs/run_test_123")
    assert mock_opener.requests[2] == ("GET", "https://mock.modtechlabs.com/outputs/processed_test.zip")


def test_mod_tech_labs_rejects_unsafe_processed_zip(temp_settings, tmp_path, monkeypatch):
    settings = load_settings()
    settings["github_ingest_provider_type"] = "mod_tech_labs"
    settings["mod_tech_labs_api_key"] = "test-api-key"
    settings["mod_tech_labs_workflow_id"] = "test-wf-uuid"
    save_settings(settings)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as z:
        z.writestr("../escape.txt", "bad")

    mock_opener = MockOpener()
    mock_opener.mock_zip_bytes = zip_buffer.getvalue()
    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: mock_opener)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    target_parent = tmp_path / "repos"
    target_parent.mkdir()

    with pytest.raises(ValueError, match="Unsafe archive member path"):
        download_and_extract_repo(
            repo_name="../unsafe_repo",
            repo_url="https://github.com/my_user/my_test_repo",
            target_parent_dir=target_parent,
        )

    assert not (tmp_path / "escape.txt").exists()
