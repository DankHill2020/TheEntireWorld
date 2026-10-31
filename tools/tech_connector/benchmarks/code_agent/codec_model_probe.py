"""Isolate model ability from the multi-file repair orchestrator on a synthetic codec."""

from __future__ import annotations

import argparse

from tech_connector.benchmarks.code_agent.holdout_cases import _envelope_codec_case
from tech_connector.services.llm_router_service import generate_llm_response


def run(model: str) -> str:
    case = _envelope_codec_case()
    prompt = (
        case.prompt
        + "\n\nExisting model source (read-only):\n```python\n"
        + case.seed_files["protocol/models.py"]
        + "\n```\n\nExisting codec source:\n```python\n"
        + case.seed_files["protocol/codec.py"]
        + "\n```\n\nReturn only a complete replacement for encode_envelope, "
        "including field validation before json.dumps. Keep the public "
        "Envelope dataclass unchanged."
    )
    return generate_llm_response(
        model,
        prompt,
        system=(
            "You are repairing one Python function using the exact supplied "
            "synthetic source. Return a complete raw function definition only. "
            "Satisfy every requested encoder behavior; do not repeat a known-bad body."
        ),
        timeout=60,
        allow_cloud_fallback=False,
        queue_category="repair",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model")
    arguments = parser.parse_args()
    print(run(arguments.model))
