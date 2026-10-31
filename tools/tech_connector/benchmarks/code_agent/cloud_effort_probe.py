"""Process-local Codex effort override for the disposable focused matrix."""

from __future__ import annotations

import argparse
import json

from tech_connector.benchmarks.code_agent.focused_lane_smoke import run
from tech_connector.services import authenticated_provider_service as account


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", choices=("openai:gpt-6-luna", "openai:gpt-6.1-sol"))
    parser.add_argument("--effort", choices=("low", "medium", "high"), required=True)
    args = parser.parse_args()

    original = account._run_provider

    def with_effort(command: list[str], **kwargs: object) -> str:
        if len(command) > 1 and command[1] == "exec":
            command = [
                *command[:2], "-c", f'model_reasoning_effort="{args.effort}"',
                *command[2:],
            ]
        return original(command, **kwargs)

    account._run_provider = with_effort
    for row in run(args.model):
        print(json.dumps(row), flush=True)


if __name__ == "__main__":
    main()
