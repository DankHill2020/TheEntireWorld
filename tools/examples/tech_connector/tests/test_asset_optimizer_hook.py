"""Tests for the post-extraction Asset Optimization hook during repository ingestion."""

import json
from pathlib import Path
import pytest

from tech_connector.services.settings_service import load_settings, save_settings, SETTINGS_PATH
from tech_connector.services.github_ingest_service import ingest_github_repo, GitHubRepoRef


@pytest.fixture
def temp_settings():
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


def test_asset_optimization_hook_execution(temp_settings, tmp_path, monkeypatch):
    """Verify that a custom asset optimizer's optimize_assets function runs after download."""
    
    # Write mock optimizer code
    optimizer_code = """
import json
from pathlib import Path

def optimize_assets(workspace_dir):
    # Write a marker file to verify execution
    marker = Path(workspace_dir) / "optimized_marker.json"
    marker.write_text(json.dumps({"optimized": True}))
"""
    optimizer_path = Path("mock_asset_optimizer.py")
    optimizer_path.write_text(optimizer_code, encoding="utf-8")

    try:
        settings = load_settings()
        settings["asset_optimizer_provider_module"] = "mock_asset_optimizer"
        save_settings(settings)

        # Mock download_and_extract_repo to just create the directory
        def mock_download(*args, **kwargs):
            dest = tmp_path / "my_downloaded_repo"
            dest.mkdir(parents=True, exist_ok=True)
            return dest

        from tech_connector.services import github_ingest_service
        monkeypatch.setattr(github_ingest_service, "download_and_extract_repo", mock_download)

        ref = GitHubRepoRef(
            owner="test_owner",
            repo="test_repo",
            ref=None,
            ref_kind="branch"
        )
        
        res = ingest_github_repo(ref, tmp_path / "my_downloaded_repo")
        assert res["ok"] is True
        
        # Verify the marker file exists, proving optimize_assets executed!
        marker_file = tmp_path / "my_downloaded_repo" / "optimized_marker.json"
        assert marker_file.exists()
        
        marker_data = json.loads(marker_file.read_text())
        assert marker_data["optimized"] is True

    finally:
        if optimizer_path.exists():
            optimizer_path.unlink()
