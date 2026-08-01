"""Run one request through Tech Connector's shared reasoning runtime."""

from __future__ import annotations

import json
import os
from pathlib import Path

from tech_connector.api import create_api


def project_root() -> Path:
    configured = os.environ.get("TECH_CONNECTOR_PROJECT_ROOT", "").strip()
    return Path(configured or Path.cwd()).expanduser().resolve()


def main() -> None:
    api = create_api(project_root=project_root())
    status = api.verify_license()
    if not status.get("connected"):
        raise SystemExit(status.get("reason") or "Log in to Tech Connector first.")

    capabilities = api.reasoning.capabilities()
    print(
        f"Tech Connector API {capabilities['api_version']} "
        f"with {capabilities['feature_manifest']['feature_count']} features"
    )

    def on_progress(event: dict) -> None:
        current = int(event.get("current") or 0)
        total = int(event.get("total") or 0)
        suffix = f" ({current}/{total})" if total else ""
        print(f"[{event.get('stage')}] {event.get('message')}{suffix}")

    result = api.reasoning.run(
        "Find the implementation of create_rig_mapping and explain its dependencies",
        context={
            "active_tab": "API",
            "project_roots": [str(project_root())],
        },
        progress_callback=on_progress,
    )
    if not result.ok:
        raise SystemExit(result.error)

    print(json.dumps(result.result["response"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

