from __future__ import annotations

"""Generate optional prompt-route fuzz mutations with a local Ollama model.

This script is intentionally not part of the normal test path. It writes review
candidates that can be promoted into tests/fixtures/prompt_route_fuzz_cases.json.
"""

import argparse
import json
from pathlib import Path
from typing import Any


def generate_mutations(prompt: str, *, count: int = 8, model: str = "") -> list[str]:
    from tech_connector.services.llm_router_service import generate_llm_response
    from tech_connector.services.ollama_service import FAST_CODE_MODEL, model_for_role

    model_name = model or model_for_role("code", FAST_CODE_MODEL)
    system = (
        "Generate realistic user prompt variants for router testing. Include slang, "
        "typos, abbreviations, and extreme brevity. Return ONLY a JSON array of strings."
    )
    raw = generate_llm_response(
        model=model_name,
        prompt=f"Ground truth prompt: {prompt}\nMutation count: {count}",
        system=system,
        response_format="json",
        options={"temperature": 0.6, "num_predict": 500},
        timeout=30,
    )
    data = _extract_json_array(raw)
    return [str(item).strip() for item in data if str(item).strip()][:count]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt", help="Ground-truth prompt to mutate.")
    parser.add_argument("--expected-route", action="append", default=[], help="Expected route. May be passed more than once.")
    parser.add_argument("--id", default="", help="Stable case id for the review output.")
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--model", default="")
    parser.add_argument("--output", default="tech_connector/scripts/prompt_route_mutation_candidates.json")
    args = parser.parse_args()

    mutations = generate_mutations(args.prompt, count=args.count, model=args.model)
    payload: dict[str, Any] = {
        "id": args.id or "review_candidate",
        "ground_truth": args.prompt,
        "expected_routes": args.expected_route,
        "mutations": [args.prompt, *[item for item in mutations if item != args.prompt]],
        "review_status": "candidate",
    }
    output = Path(args.output)
    existing = []
    if output.exists():
        try:
            existing = json.loads(output.read_text(encoding="utf-8"))
        except Exception:
            existing = []
    if not isinstance(existing, list):
        existing = []
    existing.append(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    print(f"Wrote {len(payload['mutations'])} mutation candidate(s) to {output}")
    return 0


def _extract_json_array(raw: str) -> list[Any]:
    text = str(raw or "").strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else []
    except Exception:
        pass
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            return data if isinstance(data, list) else []
        except Exception:
            return []
    return []


if __name__ == "__main__":
    raise SystemExit(main())
