"""Maintain a canonical conversation while using the reasoning API."""

from __future__ import annotations

import os
from pathlib import Path

from tech_connector.api import create_api


def main() -> None:
    root = Path(
        os.environ.get("TECH_CONNECTOR_PROJECT_ROOT", "") or Path.cwd()
    ).expanduser().resolve()
    api = create_api(project_root=root)
    thread: list[dict[str, str]] = []

    prompts = [
        "We are improving the Maya-to-Unreal animation sync pipeline.",
        "Find the exporter and importer implementations involved.",
        "Now identify where integer progress callbacks should be connected.",
    ]

    for prompt in prompts:
        result = api.reasoning.run(
            prompt,
            context={
                "project_roots": [str(root)],
                "thread": thread,
            },
        )
        if not result.ok:
            raise SystemExit(result.error)

        response = result.result["response"]
        response_text = str(response.get("text") or "")
        thread.append({"role": "user", "content": prompt})
        thread.append({"role": "assistant", "content": response_text})
        print(f"\n{response.get('action')}: {response_text}")


if __name__ == "__main__":
    main()

