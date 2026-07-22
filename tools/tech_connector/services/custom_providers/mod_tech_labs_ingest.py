"""MOD Tech Labs Custom GitHub Ingestion Provider."""

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional


def download_and_extract_repo(
    repo_name: str, 
    repo_url: str, 
    target_parent_dir: Path, 
    progress_cb: Optional[Callable] = None
) -> Path:
    """Download repository ZIP, upload/process it through MOD Tech Labs, download and extract result."""
    from tech_connector.services.settings_service import load_settings
    settings = load_settings()

    api_key = settings.get("mod_tech_labs_api_key", "").strip()
    workflow_id = settings.get("mod_tech_labs_workflow_id", "").strip()

    if not api_key or not workflow_id:
        raise ValueError("MOD Tech Labs API Key and Workflow ID must be configured in settings.")

    # 1. Resolve github zip url using default helper
    from tech_connector.services.github_ingest_service import github_zip_urls
    zip_urls = github_zip_urls(repo_url)
    if not zip_urls:
        raise ValueError(f"Could not resolve any ZIP URLs for repository URL: {repo_url}")
    source_zip_url = zip_urls[0]

    # Target directories
    target_parent_dir = Path(target_parent_dir).expanduser().resolve()
    target_parent_dir.mkdir(parents=True, exist_ok=True)
    temp_zip = target_parent_dir / f"mod_temp_{int(time.time())}.zip"

    # Emit progress
    def emit(msg, cur=0, tot=100):
        if progress_cb:
            try:
                progress_cb(msg, cur, tot)
            except Exception:
                pass

    emit("Triggering MOD Tech Labs pipeline...", 10, 100)

    # 2. Trigger Workflow Run via POST
    trigger_url = f"https://api.modtechlabs.com/v1/workflows/{workflow_id}/run"
    payload = json.dumps({
        "inputs": {
            "zip_url": source_zip_url,
            "repo_name": repo_name
        }
    }).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    req = urllib.request.Request(trigger_url, data=payload, headers=headers, method="POST")
    proxy_handler = urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(proxy_handler)

    try:
        with opener.open(req, timeout=15) as response:
            resp_data = json.loads(response.read().decode("utf-8"))
            run_id = resp_data.get("run_id") or resp_data.get("id")
            if not run_id:
                raise ValueError(f"Invalid response from MOD Tech Labs API: {resp_data}")
    except Exception as e:
        raise RuntimeError(f"Failed to trigger MOD Tech Labs workflow: {e}")

    # 3. Poll Workflow Execution until completion
    status_url = f"https://api.modtechlabs.com/v1/runs/{run_id}"
    max_attempts = 150  # 5 minutes max
    poll_interval = 2.0
    status = "running"
    output_url = None

    emit(f"MOD workflow run started (ID: {run_id}). Processing...", 20, 100)

    for attempt in range(max_attempts):
        time.sleep(poll_interval)
        try:
            status_req = urllib.request.Request(status_url, headers={"Authorization": f"Bearer {api_key}"})
            with opener.open(status_req, timeout=10) as response:
                run_info = json.loads(response.read().decode("utf-8"))
                status = str(run_info.get("status", "running")).lower()
                
                # Check outcome
                if status == "completed":
                    outputs = run_info.get("outputs", {})
                    output_url = outputs.get("processed_zip") or outputs.get("zip_url") or outputs.get("output_url")
                    break
                elif status in ("failed", "cancelled", "error"):
                    err = run_info.get("error", "Unknown workflow run error.")
                    raise RuntimeError(f"MOD Tech Labs workflow run failed: {err}")
        except Exception as e:
            # Handle transient errors gracefully during polling
            if "failed" in str(e).lower() or "error" in str(e).lower():
                raise
            continue

        emit(f"Processing in MOD Tech Labs (Status: {status})...", 20 + min(attempt, 50), 100)

    if not output_url:
        raise TimeoutError("MOD Tech Labs workflow timed out or completed without a zip output.")

    # 4. Download processed ZIP
    emit("Downloading processed workspace from MOD...", 80, 100)
    try:
        dl_req = urllib.request.Request(output_url)
        with opener.open(dl_req, timeout=30) as response:
            with open(temp_zip, "wb") as f:
                f.write(response.read())
    except Exception as e:
        raise RuntimeError(f"Failed to download MOD workflow output zip: {e}")

    # 5. Extract to target
    emit("Extracting processed files...", 90, 100)
    from tech_connector.services.github_ingest_service import _safe_repo_dir_name, safe_extract_zip_to_dir

    target_dir = target_parent_dir / _safe_repo_dir_name(repo_name, repo_url)
    target_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        safe_extract_zip_to_dir(temp_zip.read_bytes(), target_dir, progress_cb=progress_cb)
    finally:
        if temp_zip.exists():
            try:
                temp_zip.unlink()
            except Exception:
                pass

    emit(f"Ingest complete: {target_dir}", 100, 100)
    return target_dir
